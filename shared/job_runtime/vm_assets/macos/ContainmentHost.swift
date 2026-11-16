import Foundation
import Virtualization
import Security
import Darwin

private let helperProtocolVersion = 1
private let maximumArtifactBytes: Int64 = 68_719_476_736
private let frameCancel: UInt8 = 4
private let framePoweroff: UInt8 = 20
// FRAME_POWEROFF is the guest's typed stop acknowledgement ("stop_ack").

final class CancellationState {
    private let lock = NSLock()
    private var requested = false
    func request() -> Bool { lock.lock(); defer { lock.unlock() }; if requested { return false }; requested = true; return true }
    func isRequested() -> Bool { lock.lock(); defer { lock.unlock() }; return requested }
}

final class VMStopObserver: NSObject, VZVirtualMachineDelegate {
    let stopped = DispatchSemaphore(value: 0)
    private(set) var errorCode: String?

    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        stopped.signal()
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        errorCode = "vm_stopped_error"
        stopped.signal()
    }
}

private func openAbsoluteDirectory(_ path: String) throws -> Int32 {
    guard path.hasPrefix("/") else { throw HelperFailure.rejected("absolute_directory") }
    var current = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC)
    guard current >= 0 else { throw HelperFailure.rejected("absolute_directory") }
    do {
        for component in path.split(separator: "/").map(String.init) {
            let next = openat(current, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard next >= 0 else { throw HelperFailure.rejected("ancestor_open") }
            close(current); current = next
        }
        return current
    } catch {
        close(current); throw error
    }
}

struct PinnedReference {
    let descriptor: Int32
    let url: URL
}

struct PinnedOutput {
    let parentDescriptor: Int32
    let name: String
}

final class PathPolicy {
    let root: URL
    let requestDescriptor: Int32
    private let rootDescriptor: Int32
    private var held: [Int32] = []

    init(requestPath: String) throws {
        guard requestPath.hasPrefix("/"), !requestPath.contains("\0") else {
            throw HelperFailure.rejected("request_path")
        }
        let requestURL = URL(fileURLWithPath: requestPath).standardizedFileURL
        root = requestURL.deletingLastPathComponent()
        rootDescriptor = try openAbsoluteDirectory(root.path)
        let requestName = requestURL.lastPathComponent
        requestDescriptor = openat(rootDescriptor, requestName, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard requestDescriptor >= 0 else { close(rootDescriptor); throw HelperFailure.rejected("request_file") }
        var metadata = stat()
        guard fstat(rootDescriptor, &metadata) == 0,
              (metadata.st_mode & S_IFMT) == S_IFDIR,
              metadata.st_uid == geteuid(), (metadata.st_mode & 0o077) == 0 else {
            close(requestDescriptor); close(rootDescriptor); throw HelperFailure.rejected("request_parent")
        }
        var requestMetadata = stat()
        guard fstat(requestDescriptor, &requestMetadata) == 0,
              (requestMetadata.st_mode & S_IFMT) == S_IFREG,
              requestMetadata.st_uid == geteuid(), (requestMetadata.st_mode & 0o077) == 0 else {
            close(requestDescriptor); close(rootDescriptor); throw HelperFailure.rejected("request_file")
        }
    }

    deinit {
        for descriptor in held { close(descriptor) }
        close(requestDescriptor)
        close(rootDescriptor)
    }

    private func components(_ path: String, in directory: String) throws -> [String] {
        let expected = root.appendingPathComponent(directory, isDirectory: true).path + "/"
        guard path.hasPrefix(expected), !path.contains("\0") else {
            throw HelperFailure.rejected("path_scope")
        }
        let suffix = String(path.dropFirst(expected.count))
        let parts = suffix.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw HelperFailure.rejected("path_scope")
        }
        return parts
    }

    private func openDirectory(_ directory: String) throws -> Int32 {
        let descriptor = openat(rootDescriptor, directory, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw HelperFailure.rejected("authority_open") }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, metadata.st_uid == geteuid(),
              (metadata.st_mode & 0o077) == 0 else {
            close(descriptor); throw HelperFailure.rejected("authority_metadata")
        }
        held.append(descriptor)
        return descriptor
    }

    func pinExisting(_ path: String, in directory: String, directoryExpected: Bool = false) throws -> PinnedReference {
        let parts = try components(path, in: directory)
        var parent = try openDirectory(directory)
        for component in parts.dropLast() {
            let next = openat(parent, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard next >= 0 else { throw HelperFailure.rejected("ancestor_open") }
            held.append(next); parent = next
        }
        let flags = O_RDONLY | O_NOFOLLOW | O_CLOEXEC | (directoryExpected ? O_DIRECTORY : 0)
        let descriptor = openat(parent, parts.last!, flags)
        guard descriptor >= 0 else { throw HelperFailure.rejected("reference_open") }
        var metadata = stat()
        let expectedType = directoryExpected ? S_IFDIR : S_IFREG
        guard fstat(descriptor, &metadata) == 0, (metadata.st_mode & S_IFMT) == expectedType,
              metadata.st_uid == geteuid(), (metadata.st_mode & 0o077) == 0 else {
            close(descriptor); throw HelperFailure.rejected("reference_metadata")
        }
        held.append(descriptor)
        return PinnedReference(descriptor: descriptor,
            url: URL(fileURLWithPath: "/dev/fd/\(descriptor)"))
    }

    func createSnapshotDirectory() throws -> (String, Int32) {
        let name = ".vm-snapshot-" + UUID().uuidString.lowercased()
        guard mkdirat(rootDescriptor, name, 0o700) == 0 else {
            throw HelperFailure.runtime("snapshot_directory")
        }
        let descriptor = openat(rootDescriptor, name,
            O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else {
            unlinkat(rootDescriptor, name, AT_REMOVEDIR)
            throw HelperFailure.runtime("snapshot_directory")
        }
        held.append(descriptor)
        return (name, descriptor)
    }

    func pinCreatedFile(directory: Int32, role: String, writable: Bool) throws -> PinnedReference {
        guard (role == "cow") == writable,
              ["kernel", "initramfs", "root", "cow"].contains(role) else {
            throw HelperFailure.rejected("snapshot_access_role")
        }
        let access = writable ? O_RDWR : O_RDONLY
        let descriptor = openat(directory, role, access | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw HelperFailure.runtime("snapshot_missing") }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0,
              (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == geteuid(), (metadata.st_mode & 0o077) == 0,
              fsync(descriptor) == 0 else {
            close(descriptor); throw HelperFailure.runtime("snapshot_metadata")
        }
        held.append(descriptor)
        return PinnedReference(descriptor: descriptor,
            url: URL(fileURLWithPath: "/dev/fd/\(descriptor)"))
    }

    func removeSnapshotDirectory(name: String, descriptor: Int32, files: [String]) {
        for file in files { unlinkat(descriptor, file, 0) }
        unlinkat(rootDescriptor, name, AT_REMOVEDIR)
    }

    func pinNew(_ path: String, in directory: String) throws -> PinnedOutput {
        let parts = try components(path, in: directory)
        guard parts.count == 1 else { throw HelperFailure.rejected("output_scope") }
        let parent = try openDirectory(directory)
        var metadata = stat()
        guard fstatat(parent, parts[0], &metadata, AT_SYMLINK_NOFOLLOW) != 0, errno == ENOENT else {
            throw HelperFailure.rejected("output_exists")
        }
        return PinnedOutput(parentDescriptor: parent, name: parts[0])
    }
}

struct FramedChannel {
    let descriptor: Int32
    let maximumBytes: Int
    let deadline: DispatchTime

    init(descriptor: Int32, maximumBytes: Int, deadline: DispatchTime) throws {
        guard fcntl(descriptor, F_SETNOSIGPIPE, 1) == 0 else {
            throw HelperFailure.runtime("channel_setup")
        }
        self.descriptor = descriptor
        self.maximumBytes = maximumBytes
        self.deadline = deadline
    }

    private func wait(_ events: Int16) throws {
        var item = pollfd(fd: descriptor, events: events, revents: 0)
        let now = DispatchTime.now().uptimeNanoseconds
        let remaining = deadline.uptimeNanoseconds > now
            ? deadline.uptimeNanoseconds - now : 0
        let milliseconds = min(Int(remaining / 1_000_000), Int(Int32.max))
        guard milliseconds > 0, poll(&item, 1, Int32(milliseconds)) > 0,
              item.revents & events != 0,
              item.revents & Int16(POLLERR | POLLNVAL) == 0 else {
            throw HelperFailure.runtime("channel_timeout")
        }
    }

    private func writeAll(_ data: Data) throws {
        try data.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                try wait(Int16(POLLOUT))
                let count = Darwin.write(descriptor, raw.baseAddress!.advanced(by: offset), raw.count - offset)
                guard count > 0 else { throw HelperFailure.runtime("channel_write") }
                offset += count
            }
        }
    }

    private func readExactly(_ count: Int) throws -> Data {
        var data = Data(count: count)
        try data.withUnsafeMutableBytes { raw in
            var offset = 0
            while offset < count {
                try wait(Int16(POLLIN))
                let received = Darwin.read(descriptor, raw.baseAddress!.advanced(by: offset), count - offset)
                guard received > 0 else { throw HelperFailure.runtime("channel_read") }
                offset += received
            }
        }
        return data
    }

    func send(type: UInt8, payload: Data = Data()) throws {
        guard payload.count <= maximumBytes else { throw HelperFailure.rejected("frame_too_large") }
        var length = UInt32(payload.count).bigEndian
        var header = withUnsafeBytes(of: &length) { Data($0) }
        header.append(type)
        try writeAll(header)
        try writeAll(payload)
    }

    func receive() throws -> (UInt8, Data) {
        let header = try readExactly(5)
        let length = header.prefix(4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self).bigEndian }
        guard length <= UInt32(maximumBytes) else { throw HelperFailure.rejected("frame_too_large") }
        return (header[4], try readExactly(Int(length)))
    }
}

final class ContainmentHost {
    private let request: HostRequest
    private let policy: PathPolicy
    private let observer = VMStopObserver()
    private let vmQueue = DispatchQueue(label: "containment.vm")
    private var virtualMachine: VZVirtualMachine?
    private var consoleInput: Pipe?
    private var consoleOutput: Pipe?
    private var snapshotName: String?
    private var snapshotDescriptor: Int32?
    private var pinnedArtifacts: [String: URL] = [:]
    private var artifactSources: [String: PinnedReference] = [:]
    private var pinnedMounts: [String: PinnedReference] = [:]
    private var pinnedPrompt: Data?
    private var outputTarget: PinnedOutput?
    private var receiptTarget: PinnedOutput?

    init(request: HostRequest, policy: PathPolicy) {
        self.request = request
        self.policy = policy
    }

    private func validateContract() throws {
        guard let memoryMiB = UInt64(exactly: request.resources.memoryMiB),
              memoryMiB <= UInt64.max / 1_048_576 else {
            throw HelperFailure.rejected("contract_limits")
        }
        let memoryBytes = memoryMiB * 1_048_576
        guard request.protocolVersion == helperProtocolVersion,
              request.nonce.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              request.resources.cpuCount >= VZVirtualMachineConfiguration.minimumAllowedCPUCount,
              request.resources.cpuCount <= VZVirtualMachineConfiguration.maximumAllowedCPUCount,
              memoryBytes >= VZVirtualMachineConfiguration.minimumAllowedMemorySize,
              memoryBytes <= VZVirtualMachineConfiguration.maximumAllowedMemorySize,
              (1...86_400).contains(request.resources.maxRuntimeSeconds),
              (1...300).contains(request.resources.shutdownGraceSeconds),
              (1_024...16_777_216).contains(request.resources.maxFrameBytes),
              (1...16_777_216).contains(request.resources.maxOutputBytes),
              (1...1_099_511_627_776).contains(request.resources.maxDiskBytes),
              request.requestSHA256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              request.artifactGeneration.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              request.artifacts.guestAgent.sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              request.artifacts.guestAgent.bakedInto == "rootDisk",
              request.execution.strictContainment,
              request.sockets.controlPort >= 1024,
              request.sockets.stdioPort >= 1024,
              request.sockets.controlPort != request.sockets.stdioPort,
              request.io.outputPath != request.receiptPath,
              request.mounts.count <= 16 else {
            throw HelperFailure.rejected("contract_limits")
        }
        let digests = [request.artifacts.kernel, request.artifacts.initramfs,
                       request.artifacts.rootDisk, request.artifacts.cowDisk, request.io.prompt]
        guard digests.allSatisfy({ $0.sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil }) else {
            throw HelperFailure.rejected("digest_format")
        }
        var environmentNames = Set<String>()
        for item in request.execution.env {
            let secretLike = item.name.range(of: "(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH|COOKIE)",
                                             options: [.regularExpression, .caseInsensitive]) != nil
            let tokenLike = item.reference.range(of: "^(sk|pk|ghp|github_pat|xox[baprs]|eyJ)[-_.A-Za-z0-9]{8,}$",
                                                  options: [.regularExpression, .caseInsensitive]) != nil
            guard item.name.range(of: "^[A-Z][A-Z0-9_]{0,63}$", options: .regularExpression) != nil,
                  item.reference.range(of: "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", options: .regularExpression) != nil,
                  !secretLike, !tokenLike, environmentNames.insert(item.name).inserted else {
                throw HelperFailure.rejected("environment_contract")
            }
        }
        var tags = Set<String>()
        for mount in request.mounts {
            let allowedMount = (mount.role == "input" && mount.readOnly && mount.guestPath.hasPrefix("/input")) ||
                (["auth", "run", "output"].contains(mount.role) && !mount.readOnly && mount.guestPath.hasPrefix("/" + mount.role))
            guard allowedMount,
                  mount.tag.range(of: "^[A-Za-z0-9._-]{1,36}$", options: .regularExpression) != nil,
                  tags.insert(mount.tag).inserted else {
                throw HelperFailure.rejected("mount_contract")
            }
        }
    }

    private func validateFiles() throws {
        let artifacts: [(String, LockedFile)] = [("kernel", request.artifacts.kernel),
            ("initramfs", request.artifacts.initramfs), ("root", request.artifacts.rootDisk),
            ("cow", request.artifacts.cowDisk)]
        var identities = Set<String>()
        for (role, artifact) in artifacts {
            let pinned = try policy.pinExisting(artifact.path, in: "artifacts")
            var metadata = stat()
            guard fstat(pinned.descriptor, &metadata) == 0,
                  identities.insert("\(metadata.st_dev):\(metadata.st_ino)").inserted else {
                throw HelperFailure.rejected("artifact_identity")
            }
            try SecureFiles.verifyPinnedLarge(pinned.descriptor, sha256: artifact.sha256,
                                               maximumBytes: maximumArtifactBytes)
            artifactSources[role] = pinned
        }
        let manifestRef = try policy.pinExisting(request.artifacts.guestAgent.rootManifest.path,
                                                  in: "artifacts")
        let manifest = try SecureFiles.verifyPinned(manifestRef.descriptor,
            sha256: request.artifacts.guestAgent.rootManifest.sha256,
            maximumBytes: SecureFiles.maximumProfileBytes)
        guard String(data: manifest, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
                == request.artifacts.guestAgent.sha256 else {
            throw HelperFailure.rejected("guest_agent_not_baked")
        }
        let promptRef = try policy.pinExisting(request.io.prompt.path, in: "io")
        pinnedPrompt = try SecureFiles.verifyPinned(promptRef.descriptor,
            sha256: request.io.prompt.sha256, maximumBytes: request.resources.maxFrameBytes)
        outputTarget = try policy.pinNew(request.io.outputPath, in: "io")
        receiptTarget = try policy.pinNew(request.receiptPath, in: "receipts")

        for mount in request.mounts {
            pinnedMounts[mount.tag] = try policy.pinExisting(
                mount.sourcePath, in: "mounts", directoryExpected: true)
        }
        switch request.network.mode {
        case "disabled":
            guard request.network.profile == nil else { throw HelperFailure.rejected("network_profile") }
        case "unrestrictedNat":
            guard let profile = request.network.profile else { throw HelperFailure.rejected("network_profile") }
            let pinned = try policy.pinExisting(profile.path, in: "profiles")
            let data = try SecureFiles.verifyPinned(pinned.descriptor, sha256: profile.sha256,
                                                     maximumBytes: SecureFiles.maximumProfileBytes)
            try ExactSchema.validateNetworkProfile(data)
            let decoded = try JSONDecoder().decode(NetworkProfile.self, from: data)
            guard decoded.profileVersion == 1, decoded.mode == "unrestrictedNat" else {
                throw HelperFailure.rejected("network_profile")
            }
        default: throw HelperFailure.rejected("network_mode")
        }
    }

    private func preparePinnedArtifacts() throws {
        let (name, directory) = try policy.createSnapshotDirectory()
        snapshotName = name; snapshotDescriptor = directory
        let artifacts: [(String, LockedFile)] = [("kernel", request.artifacts.kernel),
            ("initramfs", request.artifacts.initramfs), ("root", request.artifacts.rootDisk),
            ("cow", request.artifacts.cowDisk)]
        do {
            for (role, artifact) in artifacts {
                guard let source = artifactSources[role],
                      fclonefileat(source.descriptor, directory, role, UInt32(CLONE_NOFOLLOW)) == 0,
                      fchmodat(directory, role, 0o600, 0) == 0 else {
                    throw HelperFailure.runtime("snapshot_clone")
                }
                let pinned = try policy.pinCreatedFile(
                    directory: directory, role: role, writable: role == "cow")
                try SecureFiles.verifyPinnedLarge(pinned.descriptor, sha256: artifact.sha256,
                                                   maximumBytes: maximumArtifactBytes)
                pinnedArtifacts[role] = pinned.url
            }
        } catch { cleanupPinnedArtifacts(); throw error }
    }

    private func cleanupPinnedArtifacts() {
        if let name = snapshotName, let descriptor = snapshotDescriptor {
            policy.removeSnapshotDirectory(name: name, descriptor: descriptor,
                                           files: Array(pinnedArtifacts.keys))
        }
        pinnedArtifacts.removeAll(); snapshotName = nil; snapshotDescriptor = nil
    }

    private func pinned(_ role: String) throws -> URL {
        guard let url = pinnedArtifacts[role] else { throw HelperFailure.runtime("snapshot_missing") }
        return url
    }

    private func configure() throws -> VZVirtualMachineConfiguration {
        let configuration = VZVirtualMachineConfiguration()
        let boot = VZLinuxBootLoader(kernelURL: try pinned("kernel"))
        boot.initialRamdiskURL = try pinned("initramfs")
        boot.commandLine = "console=hvc0 panic=-1"
        configuration.bootLoader = boot
        configuration.cpuCount = request.resources.cpuCount
        configuration.memorySize = UInt64(request.resources.memoryMiB) * 1_048_576

        let rootAttachment = try VZDiskImageStorageDeviceAttachment(
            url: try pinned("root"), readOnly: true)
        let cowAttachment = try VZDiskImageStorageDeviceAttachment(
            url: try pinned("cow"), readOnly: false)
        configuration.storageDevices = [
            VZVirtioBlockDeviceConfiguration(attachment: rootAttachment),
            VZVirtioBlockDeviceConfiguration(attachment: cowAttachment)
        ]

        let input = Pipe()
        let output = Pipe()
        let console = VZVirtioConsoleDeviceConfiguration()
        let port = VZVirtioConsolePortConfiguration()
        port.isConsole = true
        port.attachment = VZFileHandleSerialPortAttachment(
            fileHandleForReading: input.fileHandleForReading,
            fileHandleForWriting: output.fileHandleForWriting)
        console.ports[0] = port
        output.fileHandleForReading.readabilityHandler = { handle in
            _ = try? handle.read(upToCount: 65_536)
        }
        consoleInput = input
        consoleOutput = output
        configuration.consoleDevices = [console]
        configuration.socketDevices = [VZVirtioSocketDeviceConfiguration()]

        configuration.directorySharingDevices = try request.mounts.map { mount in
            let device = VZVirtioFileSystemDeviceConfiguration(tag: mount.tag)
            guard let source = pinnedMounts[mount.tag] else { throw HelperFailure.runtime("mount_pin_missing") }
            let directory = VZSharedDirectory(url: source.url, readOnly: mount.readOnly)
            device.share = VZSingleDirectoryShare(directory: directory)
            return device
        }

        if request.network.mode == "unrestrictedNat" {
            let network = VZVirtioNetworkDeviceConfiguration()
            network.attachment = VZNATNetworkDeviceAttachment()
            configuration.networkDevices = [network]
        } else {
            configuration.networkDevices = []
        }
        try configuration.validate()
        return configuration
    }

    private func start(_ vm: VZVirtualMachine, timeout: DispatchTime) throws {
        let completed = DispatchSemaphore(value: 0)
        var failure: Error?
        vm.start { result in
            if case .failure(let error) = result { failure = error }
            completed.signal()
        }
        guard completed.wait(timeout: timeout) == .success else { throw HelperFailure.runtime("start_timeout") }
        guard failure == nil else { throw HelperFailure.runtime("start_failed") }
    }

    private func connect(_ socket: VZVirtioSocketDevice, port: UInt32, timeout: DispatchTime) throws -> VZVirtioSocketConnection {
        let completed = DispatchSemaphore(value: 0)
        var result: Result<VZVirtioSocketConnection, Error>?
        socket.connect(toPort: port) { value in
            result = value
            completed.signal()
        }
        guard completed.wait(timeout: timeout) == .success else { throw HelperFailure.runtime("connect_timeout") }
        guard case .success(let connection) = result else { throw HelperFailure.runtime("connect_failed") }
        return connection
    }

    private func forceStop(_ vm: VZVirtualMachine) -> Bool {
        let completed = DispatchSemaphore(value: 0)
        var succeeded = false
        vm.stop { error in
            succeeded = (error == nil)
            completed.signal()
        }
        return completed.wait(timeout: .now() + .seconds(request.resources.shutdownGraceSeconds)) == .success
            && succeeded
    }

    private func metadata(type: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "protocolVersion": helperProtocolVersion,
            "type": type,
            "requestID": request.requestID.uuidString.lowercased(),
            "nonce": request.nonce
        ], options: [.sortedKeys])
    }

    private func requireMetadata(_ data: Data, type: String) throws {
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(value.keys) == Set(["protocolVersion", "type", "requestID", "nonce"]),
              value["protocolVersion"] as? Int == helperProtocolVersion,
              value["type"] as? String == type,
              value["requestID"] as? String == request.requestID.uuidString.lowercased(),
              value["nonce"] as? String == request.nonce else {
            throw HelperFailure.rejected("guest_metadata")
        }
    }

    func run() throws -> TeardownReceipt {
        try validateContract()
        try validateFiles()
        try preparePinnedArtifacts()
        defer { cleanupPinnedArtifacts() }
        let configuration = try configure()
        let vm = VZVirtualMachine(configuration: configuration, queue: vmQueue)
        virtualMachine = vm
        vm.delegate = observer

        let started = Date()
        let runtimeDeadline = DispatchTime.now() + .seconds(request.resources.maxRuntimeSeconds)
        var acknowledged = false
        var teardownConfirmed = false
        var output = Data()
        var guestExitCode: Int?
        var guestSignal: Int?
        var publicError: String?

        do {
            try start(vm, timeout: runtimeDeadline)
            guard let socket = vm.socketDevices.first as? VZVirtioSocketDevice else {
                throw HelperFailure.runtime("socket_missing")
            }
            let stdio = try connect(socket, port: request.sockets.stdioPort, timeout: runtimeDeadline)
            let stdioChannel = try FramedChannel(descriptor: stdio.fileDescriptor,
                maximumBytes: request.resources.maxFrameBytes, deadline: runtimeDeadline)
            let cancellation = CancellationState()
            signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN)
            let termSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: vmQueue)
            let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: vmQueue)
            for source in [termSource, intSource] {
                source.setEventHandler {
                    if cancellation.request() { try? stdioChannel.send(type: frameCancel) }
                }
                source.resume()
            }
            defer { termSource.cancel(); intSource.cancel() }
            let guestRequest = try JSONSerialization.data(withJSONObject: [
                "schema": "trading-agent.guest-exec", "version": helperProtocolVersion,
                "nonce": request.nonce,
                "nonce_digest": SecureFiles.digest(Data(request.nonce.utf8)),
                "request_id": request.requestID.uuidString.lowercased(),
                "request_sha256": request.requestSHA256,
                "artifact_generation": request.artifactGeneration,
                "action": "run", "executable": request.execution.executable, "argv": request.execution.argv,
                "env": Dictionary(uniqueKeysWithValues: request.execution.env.map { ($0.name, $0.reference) }),
                "timeout_ms": request.resources.maxRuntimeSeconds * 1_000,
                "strict_containment": request.execution.strictContainment
            ], options: [.sortedKeys])
            try stdioChannel.send(type: 1, payload: guestRequest) // FRAME_REQUEST
            guard let prompt = pinnedPrompt else { throw HelperFailure.runtime("prompt_pin_missing") }
            try stdioChannel.send(type: 2, payload: prompt)       // FRAME_PROMPT
            try stdioChannel.send(type: 3)                        // FRAME_PROMPT_END
            var exitSeen = false
            var poweroffSeen = false
            while !poweroffSeen {
                let (type, payload) = try stdioChannel.receive()
                switch type {
                case 16, 17: // FRAME_STDOUT / FRAME_STDERR
                    guard output.count <= request.resources.maxOutputBytes - payload.count else {
                        try? stdioChannel.send(type: frameCancel)  // FRAME_CANCEL
                        throw HelperFailure.runtime("output_limit")
                    }
                    output.append(payload)
                case 18: // FRAME_EXIT
                    let reported = try ExactSchema.validateGuestFrame(payload, type: type, request: request)
                    guard reported == output.count,
                          let exit = try JSONSerialization.jsonObject(with: payload) as? [String: Any] else {
                        throw HelperFailure.rejected("guest_output_mismatch")
                    }
                    guestExitCode = exit["returncode"] as? Int
                    guestSignal = exit["signal"] as? Int
                    guard guestExitCode != nil || guestSignal != nil else {
                        throw HelperFailure.rejected("guest_exit_missing")
                    }
                    exitSeen = true
                case framePoweroff: // FRAME_POWEROFF / stop_ack
                    _ = try ExactSchema.validateGuestFrame(payload, type: type, request: request)
                    poweroffSeen = true
                    acknowledged = true
                case 19: throw HelperFailure.runtime("guest_error")
                default: throw HelperFailure.rejected("guest_frame")
                }
            }
            guard exitSeen else { throw HelperFailure.rejected("guest_state") }
            guard let target = outputTarget else { throw HelperFailure.runtime("output_pin_missing") }
            try SecureFiles.writeNewPrivateFile(output, parent: target.parentDescriptor, finalName: target.name)
            let stopDeadline = DispatchTime.now() + .seconds(request.resources.shutdownGraceSeconds)
            try vm.requestStop()
            if observer.stopped.wait(timeout: stopDeadline) != .success {
                throw HelperFailure.runtime("stop_timeout")
            }
            teardownConfirmed = true
            if let code = observer.errorCode { throw HelperFailure.runtime(code) }
            if cancellation.isRequested() { throw HelperFailure.runtime("cancelled") }
        } catch let failure as HelperFailure {
            publicError = failure.publicCode
            if !teardownConfirmed { teardownConfirmed = forceStop(vm) }
            if !teardownConfirmed { publicError = "teardown_unknown" }
        } catch {
            publicError = "vm_runtime"
            if !teardownConfirmed { teardownConfirmed = forceStop(vm) }
            if !teardownConfirmed { publicError = "teardown_unknown" }
        }

        consoleOutput?.fileHandleForReading.readabilityHandler = nil
        let stoppedAt = Date()
        let receipt = TeardownReceipt(
            protocolVersion: helperProtocolVersion,
            requestID: request.requestID,
            requestSHA256: request.requestSHA256,
            artifactGeneration: request.artifactGeneration,
            nonceDigest: SecureFiles.digest(Data(request.nonce.utf8)),
            outcome: publicError == nil ? "completed" : "failed",
            stopAcknowledged: acknowledged,
            teardownConfirmed: teardownConfirmed,
            startedAt: ISO8601DateFormatter().string(from: started),
            stoppedAt: ISO8601DateFormatter().string(from: stoppedAt),
            elapsedMilliseconds: max(0, Int(stoppedAt.timeIntervalSince(started) * 1_000)),
            outputBytes: output.count,
            exitCode: guestExitCode,
            terminationSignal: guestSignal,
            errorCode: publicError)
        let receiptData = try JSONEncoder().encode(receipt)
        guard let target = receiptTarget else { throw HelperFailure.runtime("receipt_pin_missing") }
        try SecureFiles.writeNewPrivateFile(receiptData, parent: target.parentDescriptor, finalName: target.name)
        if let publicError { throw HelperFailure.runtime(publicError) }
        return receipt
    }
}

@main
struct ContainmentHostMain {
    static func main() {
        guard CommandLine.arguments.count == 3,
              CommandLine.arguments[1] == "--request-file" else {
            fail("usage")
        }
        do {
            guard #available(macOS 14.0, *) else { throw HelperFailure.unsupported("unsupported_host") }
            guard hasVirtualizationEntitlement() else {
                throw HelperFailure.unsupported("missing_virtualization_entitlement")
            }
            let requestPath = CommandLine.arguments[2]
            let policy = try PathPolicy(requestPath: requestPath)
            let data = try SecureFiles.readPinned(policy.requestDescriptor,
                maximumBytes: SecureFiles.maximumRequestBytes)
            try ExactSchema.validateRequest(data)
            let request = try JSONDecoder().decode(HostRequest.self, from: data)
            _ = try ContainmentHost(request: request, policy: policy).run()
        } catch let failure as HelperFailure {
            fail(failure.publicCode)
        } catch {
            fail("helper_failure")
        }
    }

    private static func hasVirtualizationEntitlement() -> Bool {
        guard let task = SecTaskCreateFromSelf(nil),
              let value = SecTaskCopyValueForEntitlement(
                task, "com.apple.security.virtualization" as CFString, nil) else {
            return false
        }
        return (value as? Bool) == true
    }

    private static func fail(_ code: String) -> Never {
        FileHandle.standardError.write(Data(("containment-host:" + code + "\n").utf8))
        Darwin.exit(1)
    }
}
