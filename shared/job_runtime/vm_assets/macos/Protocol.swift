import Foundation
import CryptoKit
import Darwin

enum HelperFailure: Error {
    case rejected(String)
    case unsupported(String)
    case runtime(String)

    var publicCode: String {
        switch self {
        case .rejected(let code), .unsupported(let code), .runtime(let code): return code
        }
    }
}

struct LockedFile: Codable {
    let path: String
    let sha256: String
}

struct GuestAgentIdentity: Codable {
    let sha256: String
    let bakedInto: String
    let rootManifest: LockedFile
}

struct ArtifactSet: Codable {
    let kernel: LockedFile
    let initramfs: LockedFile
    let rootDisk: LockedFile
    let cowDisk: LockedFile
    let guestAgent: GuestAgentIdentity
}

struct ResourceLimits: Codable {
    let cpuCount: Int
    let memoryMiB: Int
    let maxRuntimeSeconds: Int
    let shutdownGraceSeconds: Int
    let maxFrameBytes: Int
    let maxOutputBytes: Int
    let maxDiskBytes: Int64
}

struct SocketReferences: Codable {
    let controlPort: UInt32
    let stdioPort: UInt32
}

struct MountReference: Codable {
    let role: String
    let tag: String
    let sourcePath: String
    let guestPath: String
    let readOnly: Bool
}

struct NetworkReference: Codable {
    let mode: String
    let profile: LockedFile?
}

struct IOReferences: Codable {
    let prompt: LockedFile
    let outputPath: String
}

struct GuestEnvironmentReference: Codable {
    let name: String
    let reference: String
}

struct GuestExecution: Codable {
    let executable: String
    let argv: [String]
    let env: [GuestEnvironmentReference]
    let strictContainment: Bool
}

struct HostRequest: Codable {
    let protocolVersion: Int
    let requestID: UUID
    let nonce: String
    let requestSHA256: String
    let artifactGeneration: String
    let artifacts: ArtifactSet
    let execution: GuestExecution
    let resources: ResourceLimits
    let sockets: SocketReferences
    let mounts: [MountReference]
    let network: NetworkReference
    let io: IOReferences
    let receiptPath: String
}

struct NetworkProfile: Codable {
    let profileVersion: Int
    let mode: String
}

struct TeardownReceipt: Codable {
    let protocolVersion: Int
    let requestID: UUID
    let requestSHA256: String
    let artifactGeneration: String
    let nonceDigest: String
    let outcome: String
    let stopAcknowledged: Bool
    let teardownConfirmed: Bool
    let startedAt: String?
    let stoppedAt: String
    let elapsedMilliseconds: Int
    let outputBytes: Int
    let exitCode: Int?
    let terminationSignal: Int?
    let errorCode: String?
}

struct DuplicateKeyRejector {
    private let bytes: [UInt8]
    private var index = 0

    init(_ data: Data) { bytes = Array(data) }

    mutating func validate() throws {
        skipWhitespace()
        try value()
        skipWhitespace()
        guard index == bytes.count else { throw HelperFailure.rejected("json_syntax") }
    }

    private mutating func skipWhitespace() {
        while index < bytes.count, [9, 10, 13, 32].contains(bytes[index]) { index += 1 }
    }

    private mutating func value() throws {
        skipWhitespace()
        guard index < bytes.count else { throw HelperFailure.rejected("json_syntax") }
        switch bytes[index] {
        case 123: try object()
        case 91: try array()
        case 34: _ = try string()
        default:
            let start = index
            while index < bytes.count, ![9, 10, 13, 32, 44, 93, 125].contains(bytes[index]) { index += 1 }
            guard index > start else { throw HelperFailure.rejected("json_syntax") }
        }
    }

    private mutating func object() throws {
        index += 1
        skipWhitespace()
        if consume(125) { return }
        var keys = Set<String>()
        while true {
            skipWhitespace()
            let key = try string()
            guard keys.insert(key).inserted else { throw HelperFailure.rejected("duplicate_json_key") }
            skipWhitespace()
            guard consume(58) else { throw HelperFailure.rejected("json_syntax") }
            try value()
            skipWhitespace()
            if consume(125) { return }
            guard consume(44) else { throw HelperFailure.rejected("json_syntax") }
        }
    }

    private mutating func array() throws {
        index += 1
        skipWhitespace()
        if consume(93) { return }
        while true {
            try value()
            skipWhitespace()
            if consume(93) { return }
            guard consume(44) else { throw HelperFailure.rejected("json_syntax") }
        }
    }

    private mutating func string() throws -> String {
        guard consume(34) else { throw HelperFailure.rejected("json_syntax") }
        let contentStart = index
        var escaped = false
        while index < bytes.count {
            let byte = bytes[index]
            if !escaped, byte == 34 {
                let content = Data(bytes[contentStart..<index])
                index += 1
                let wrapped = Data([91, 34]) + content + Data([34, 93])
                guard let decoded = try? JSONSerialization.jsonObject(with: wrapped) as? [String],
                      decoded.count == 1 else { throw HelperFailure.rejected("json_syntax") }
                return decoded[0]
            }
            if !escaped, byte < 32 { throw HelperFailure.rejected("json_syntax") }
            if escaped { escaped = false } else if byte == 92 { escaped = true }
            index += 1
        }
        throw HelperFailure.rejected("json_syntax")
    }

    private mutating func consume(_ byte: UInt8) -> Bool {
        guard index < bytes.count, bytes[index] == byte else { return false }
        index += 1
        return true
    }
}

enum ExactSchema {
    private static func object(_ value: Any, keys: Set<String>, at path: String) throws -> [String: Any] {
        guard let object = value as? [String: Any], Set(object.keys) == keys else {
            throw HelperFailure.rejected("schema_\(path)")
        }
        return object
    }

    private static func string(_ value: Any?, at path: String) throws -> String {
        guard let value = value as? String, !value.isEmpty else {
            throw HelperFailure.rejected("schema_\(path)")
        }
        return value
    }

    private static func integer(_ value: Any?, at path: String) throws -> Int {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID() else {
            throw HelperFailure.rejected("schema_\(path)")
        }
        let double = number.doubleValue
        guard double.isFinite, double.rounded() == double,
              double >= Double(Int.min), double <= Double(Int.max) else {
            throw HelperFailure.rejected("schema_\(path)")
        }
        return Int(double)
    }

    private static func boolean(_ value: Any?, at path: String) throws -> Bool {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else {
            throw HelperFailure.rejected("schema_\(path)")
        }
        return number.boolValue
    }

    private static func lockedFile(_ value: Any?, at path: String) throws {
        let item = try object(value as Any, keys: ["path", "sha256"], at: path)
        _ = try string(item["path"], at: "\(path)_path")
        _ = try string(item["sha256"], at: "\(path)_sha256")
    }

    static func validateRequest(_ data: Data) throws {
        var duplicateCheck = DuplicateKeyRejector(data)
        try duplicateCheck.validate()
        let raw = try JSONSerialization.jsonObject(with: data, options: [])
        let root = try object(raw, keys: [
            "protocolVersion", "requestID", "nonce", "requestSHA256", "artifactGeneration",
            "artifacts", "execution", "resources", "sockets", "mounts", "network", "io", "receiptPath"
        ], at: "root")
        _ = try integer(root["protocolVersion"], at: "protocolVersion")
        _ = try string(root["requestID"], at: "requestID")
        _ = try string(root["nonce"], at: "nonce")
        _ = try string(root["requestSHA256"], at: "requestSHA256")
        _ = try string(root["artifactGeneration"], at: "artifactGeneration")
        _ = try string(root["receiptPath"], at: "receiptPath")

        let artifacts = try object(root["artifacts"] as Any,
            keys: ["kernel", "initramfs", "rootDisk", "cowDisk", "guestAgent"], at: "artifacts")
        for key in ["kernel", "initramfs", "rootDisk", "cowDisk"] {
            try lockedFile(artifacts[key], at: "artifacts_\(key)")
        }
        let guestAgent = try object(artifacts["guestAgent"] as Any,
            keys: ["sha256", "bakedInto", "rootManifest"], at: "guestAgent")
        _ = try string(guestAgent["sha256"], at: "guestAgent_sha256")
        _ = try string(guestAgent["bakedInto"], at: "guestAgent_bakedInto")
        try lockedFile(guestAgent["rootManifest"], at: "guestAgent_rootManifest")

        let execution = try object(root["execution"] as Any,
            keys: ["executable", "argv", "env", "strictContainment"], at: "execution")
        _ = try string(execution["executable"], at: "execution_executable")
        guard execution["argv"] is [String], let environment = execution["env"] as? [Any] else {
            throw HelperFailure.rejected("schema_execution")
        }
        for item in environment {
            let entry = try object(item, keys: ["name", "reference"], at: "execution_env")
            _ = try string(entry["name"], at: "execution_env_name")
            _ = try string(entry["reference"], at: "execution_env_reference")
        }
        _ = try boolean(execution["strictContainment"], at: "execution_strictContainment")

        let resources = try object(root["resources"] as Any, keys: [
            "cpuCount", "memoryMiB", "maxRuntimeSeconds", "shutdownGraceSeconds", "maxFrameBytes",
            "maxOutputBytes", "maxDiskBytes"
        ], at: "resources")
        for key in resources.keys { _ = try integer(resources[key], at: "resources_\(key)") }

        let sockets = try object(root["sockets"] as Any,
            keys: ["controlPort", "stdioPort"], at: "sockets")
        for key in sockets.keys { _ = try integer(sockets[key], at: "sockets_\(key)") }

        guard let mounts = root["mounts"] as? [Any] else {
            throw HelperFailure.rejected("schema_mounts")
        }
        for (index, value) in mounts.enumerated() {
            let mount = try object(value, keys: ["role", "tag", "sourcePath", "guestPath", "readOnly"], at: "mount_\(index)")
            _ = try string(mount["role"], at: "mount_role")
            _ = try string(mount["tag"], at: "mount_tag")
            _ = try string(mount["sourcePath"], at: "mount_sourcePath")
            _ = try string(mount["guestPath"], at: "mount_guestPath")
            _ = try boolean(mount["readOnly"], at: "mount_readOnly")
        }

        let network = try object(root["network"] as Any, keys: ["mode", "profile"], at: "network")
        _ = try string(network["mode"], at: "network_mode")
        if !(network["profile"] is NSNull) { try lockedFile(network["profile"], at: "network_profile") }

        let io = try object(root["io"] as Any, keys: ["prompt", "outputPath"], at: "io")
        try lockedFile(io["prompt"], at: "io_prompt")
        _ = try string(io["outputPath"], at: "io_outputPath")
    }

    static func validateGuestFrame(_ data: Data, type: UInt8, request: HostRequest) throws -> Int {
        var duplicateCheck = DuplicateKeyRejector(data)
        try duplicateCheck.validate()
        let raw = try JSONSerialization.jsonObject(with: data, options: [])
        let bindings = ["schema", "version", "nonce", "nonce_digest", "request_id",
                        "request_sha256", "artifact_generation"]
        let extra = type == 18
            ? ["reason", "returncode", "signal", "timed_out", "cancelled", "output_bytes"]
            : ["requested", "reason"]
        let root = try object(raw, keys: Set(bindings + extra), at: "guest_frame")
        guard try string(root["schema"], at: "guest_schema") == "trading-agent.guest-exec",
              try integer(root["version"], at: "guest_version") == 1,
              try string(root["nonce"], at: "guest_nonce") == request.nonce,
              try string(root["nonce_digest"], at: "guest_nonce_digest") == SecureFiles.digest(Data(request.nonce.utf8)),
              try string(root["request_id"], at: "guest_request_id") == request.requestID.uuidString.lowercased(),
              try string(root["request_sha256"], at: "guest_request_sha256") == request.requestSHA256,
              try string(root["artifact_generation"], at: "guest_artifact_generation") == request.artifactGeneration else {
            throw HelperFailure.rejected("guest_binding")
        }
        if type == 18 {
            _ = try string(root["reason"], at: "guest_reason")
            if !(root["returncode"] is NSNull) { _ = try integer(root["returncode"], at: "guest_returncode") }
            if !(root["signal"] is NSNull) { _ = try integer(root["signal"], at: "guest_signal") }
            _ = try boolean(root["timed_out"], at: "guest_timed_out")
            _ = try boolean(root["cancelled"], at: "guest_cancelled")
            let count = try integer(root["output_bytes"], at: "guest_output_bytes")
            guard count >= 0, count <= request.resources.maxOutputBytes else {
                throw HelperFailure.rejected("guest_output_bounds")
            }
            return count
        }
        guard try boolean(root["requested"], at: "guest_requested"),
              try string(root["reason"], at: "guest_poweroff_reason") == "completed" else {
            throw HelperFailure.rejected("guest_poweroff")
        }
        return 0
    }

    static func validateNetworkProfile(_ data: Data) throws {
        var duplicateCheck = DuplicateKeyRejector(data)
        try duplicateCheck.validate()
        let raw = try JSONSerialization.jsonObject(with: data, options: [])
        let root = try object(raw, keys: ["profileVersion", "mode"], at: "network_profile")
        _ = try integer(root["profileVersion"], at: "network_profileVersion")
        _ = try string(root["mode"], at: "network_profileMode")
    }
}

enum SecureFiles {
    static let maximumRequestBytes = 65_536
    static let maximumProfileBytes = 4_096

    static func readPrivateRegularFile(_ path: String, maximumBytes: Int) throws -> Data {
        let descriptor = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw HelperFailure.rejected("file_open") }
        defer { close(descriptor) }

        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0,
              (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == geteuid(),
              (metadata.st_mode & 0o077) == 0,
              metadata.st_size >= 0,
              metadata.st_size <= maximumBytes else {
            throw HelperFailure.rejected("file_metadata")
        }

        var data = Data(count: Int(metadata.st_size))
        try data.withUnsafeMutableBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                guard let base = buffer.baseAddress else { throw HelperFailure.rejected("file_read") }
                let count = Darwin.read(descriptor, base.advanced(by: offset), buffer.count - offset)
                guard count > 0 else { throw HelperFailure.rejected("file_read") }
                offset += count
            }
        }
        var extra: UInt8 = 0
        guard Darwin.read(descriptor, &extra, 1) == 0 else {
            throw HelperFailure.rejected("file_changed")
        }
        return data
    }

    static func readPinned(_ descriptor: Int32, maximumBytes: Int) throws -> Data {
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == geteuid(), (metadata.st_mode & 0o077) == 0,
              metadata.st_size >= 0, metadata.st_size <= maximumBytes,
              lseek(descriptor, 0, SEEK_SET) == 0 else {
            throw HelperFailure.rejected("pinned_metadata")
        }
        var data = Data(count: Int(metadata.st_size))
        try data.withUnsafeMutableBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                let count = Darwin.read(descriptor, buffer.baseAddress!.advanced(by: offset), buffer.count - offset)
                guard count > 0 else { throw HelperFailure.rejected("pinned_read") }
                offset += count
            }
        }
        return data
    }

    static func verifyPinned(_ descriptor: Int32, sha256: String, maximumBytes: Int) throws -> Data {
        let data = try readPinned(descriptor, maximumBytes: maximumBytes)
        guard digest(data) == sha256 else { throw HelperFailure.rejected("digest_mismatch") }
        return data
    }

    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func verify(_ file: LockedFile, maximumBytes: Int) throws -> Data {
        let data = try readPrivateRegularFile(file.path, maximumBytes: maximumBytes)
        guard digest(data) == file.sha256 else { throw HelperFailure.rejected("digest_mismatch") }
        return data
    }

    static func verifyPinnedLarge(_ descriptor: Int32, sha256: String, maximumBytes: Int64) throws {
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == geteuid(), (metadata.st_mode & 0o077) == 0,
              metadata.st_size > 0, metadata.st_size <= maximumBytes,
              lseek(descriptor, 0, SEEK_SET) == 0 else {
            throw HelperFailure.rejected("artifact_metadata")
        }
        var hasher = SHA256()
        var buffer = [UInt8](repeating: 0, count: 1_048_576)
        while true {
            let count = Darwin.read(descriptor, &buffer, buffer.count)
            guard count >= 0 else { throw HelperFailure.rejected("artifact_read") }
            if count == 0 { break }
            hasher.update(data: Data(buffer[0..<count]))
        }
        guard hasher.finalize().map({ String(format: "%02x", $0) }).joined() == sha256 else {
            throw HelperFailure.rejected("digest_mismatch")
        }
    }

    static func verifyLargeFile(_ file: LockedFile, maximumBytes: Int64) throws {
        let descriptor = open(file.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        guard descriptor >= 0 else { throw HelperFailure.rejected("artifact_open") }
        defer { close(descriptor) }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0,
              (metadata.st_mode & S_IFMT) == S_IFREG,
              metadata.st_uid == geteuid(),
              (metadata.st_mode & 0o077) == 0,
              metadata.st_size > 0,
              metadata.st_size <= maximumBytes else {
            throw HelperFailure.rejected("artifact_metadata")
        }
        var hasher = SHA256()
        var buffer = [UInt8](repeating: 0, count: 1_048_576)
        while true {
            let count = Darwin.read(descriptor, &buffer, buffer.count)
            guard count >= 0 else { throw HelperFailure.rejected("artifact_read") }
            if count == 0 { break }
            hasher.update(data: Data(buffer[0..<count]))
        }
        let actual = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard actual == file.sha256 else { throw HelperFailure.rejected("digest_mismatch") }
    }

    static func writeNewPrivateFile(_ data: Data, parent: Int32, finalName: String) throws {
        guard !finalName.isEmpty, !finalName.contains("/") else {
            throw HelperFailure.runtime("output_create")
        }
        var parentMetadata = stat()
        guard fstat(parent, &parentMetadata) == 0, (parentMetadata.st_mode & S_IFMT) == S_IFDIR,
              parentMetadata.st_uid == geteuid(), (parentMetadata.st_mode & 0o077) == 0 else {
            throw HelperFailure.runtime("output_parent")
        }
        let temporaryName = ".vm-helper-" + UUID().uuidString.lowercased()
        let descriptor = openat(parent, temporaryName,
            O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard descriptor >= 0 else { throw HelperFailure.runtime("output_create") }
        var published = false
        defer {
            close(descriptor)
            if !published { unlinkat(parent, temporaryName, 0) }
        }
        try data.withUnsafeBytes { buffer in
            var offset = 0
            while offset < buffer.count {
                guard let base = buffer.baseAddress else { throw HelperFailure.runtime("output_write") }
                let count = Darwin.write(descriptor, base.advanced(by: offset), buffer.count - offset)
                guard count > 0 else { throw HelperFailure.runtime("output_write") }
                offset += count
            }
        }
        guard fsync(descriptor) == 0 else { throw HelperFailure.runtime("output_write") }
        guard renameatx_np(parent, temporaryName, parent, finalName, UInt32(RENAME_EXCL)) == 0 else {
            throw HelperFailure.runtime("output_publish")
        }
        published = true
        guard fsync(parent) == 0 else { throw HelperFailure.runtime("output_sync_unknown") }
    }
}
