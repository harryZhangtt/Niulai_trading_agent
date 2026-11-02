# Workspace setup for PencilPlaybook

This is the local adaptation of the upstream setup procedure. Read the target's
existing design system and `.pen` canvas before choosing values. Preserve the
incumbent tokens and dimensions. For a new synthetic example, choose a preset
from `presets/` that fits the request and disclose it as a default.

Keep project configuration beside its design file or under ignored
`ui/runtime/pencilplaybook/`; do not edit the installed skill or global agent
directories. A configuration records the canvas width/height, sidebar width,
content maximum and a token map. Resolve `SCAFFOLD_*` placeholders in memory from
these values before sending any design operation. Never send `YOUR_HEX`,
`YOUR_FONT` or unresolved placeholders to Pencil.

For custom dimensions derive pageAreaWidth = canvasWidth - sidebarWidth. Check
positive content dimensions for the scaffold's header/footer offsets. The
included JSON presets provide examples, not overrides of an existing app.

Before using Pencil operations, discover the actual available tool schemas and
call the editor-state read method. If no Pencil tool is available, report
`PENCIL_TOOL_UNAVAILABLE`; planning from the playbook remains possible, but do
not claim a canvas edit or screenshot. Do not install/enable an MCP server as a
side effect of setup. The official app is at https://www.pencil.dev/.
