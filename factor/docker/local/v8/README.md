# Duplicate-safe probe parsing v8

V8 preserves the fixed v7 execution boundary and changes only probe decoding.
Both Colima status and Docker context output pass through the bounded strict JSON
loader: duplicate keys, NaN/Infinity, invalid UTF-8, surrogate strings, malformed
or trailing data, and oversized payloads fail closed as sanitized v8 errors.

Production activation remains fixed and non-injectable; tests patch only private
fixed-command helpers and make no Colima or Docker calls. The profile remains
selected-disabled and binds the live frozen v7 tree and profile.
