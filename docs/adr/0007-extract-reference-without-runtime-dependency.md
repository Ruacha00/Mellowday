# Extract the reference implementation without a runtime dependency

The new root project uses `chatbot/` as a read-only source of implementation evidence. It extracts or adapts the proven Agent Core and generic backend-management behavior behind new, product-neutral interfaces, while excluding QQ/OneBot integration and bundled tool and Skill implementations.

The new runtime must not import from, package, or otherwise depend on the reference tree. This keeps the resulting assistant independently buildable, allows the reference clone to remain excluded from Git, and prevents QQ-specific assumptions from leaking into the new architecture.
