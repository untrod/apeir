def invoke(capability, payload):
    if capability != "example.echo":
        return {"ok": False, "error": "Capability is not declared"}
    return {"echo": payload.get("value", "")}