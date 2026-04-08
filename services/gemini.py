import google.generativeai as genai
from config import model


def run_agent_loop(prompt: str, tools: list, execute_fn) -> tuple[str, str]:

    gemini_tools = [
        genai.protos.Tool(
            function_declarations=[
                genai.protos.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=genai.protos.Schema(
                        type=genai.protos.Type.OBJECT,
                        properties={
                            k: _schema_to_proto(v)
                            for k, v in t["parameters"]["properties"].items()
                        },
                        required=t["parameters"].get("required", []),
                    ),
                )
            ]
        )
        for t in tools
    ]

    contents = [{"role": "user", "parts": [{"text": prompt}]}]

    final_reply = ""
    stage       = "ordering"
    max_iterations = 5
    iteration      = 0

    while iteration < max_iterations:
        iteration += 1

        response = model.generate_content(
            contents,
            tools=gemini_tools,
        )

        # ── Safe debug print — avoid calling str(response) which triggers the bug ──
        try:
            candidate = response.candidates[0]
            parts = candidate.content.parts
            safe_summary = f"[iteration {iteration}] RAW RESPONSE: candidates={len(response.candidates)}, parts={len(parts)}"
            print(safe_summary)
        except Exception as e:
            print(f"[iteration {iteration}] RAW RESPONSE: (could not summarize — {e})")
            parts = []

        if not parts:
            break
        part = parts[0]

        # ── Plain text — model is done, send to user ───────────────────────────
        if not part.function_call:
            final_reply = part.text or final_reply
            break

        tool_name = part.function_call.name
        args      = _parse_function_args(part.function_call)

        print(f"[iteration {iteration}] TOOL: {tool_name} ARGS: {args}")

        result = execute_fn(tool_name, args)
        stage  = result.get("stage", stage)

        print(f"[iteration {iteration}] RESULT: {result}")

        contents.append({
            "role": "model",
            "parts": [{"function_call": {"name": tool_name, "args": args}}]
        })
        contents.append({
            "role": "user",
            "parts": [{"function_response": {"name": tool_name, "response": result}}]
        })

        # ── Escalate → break immediately, supervisor handles it ────────────────
        if tool_name == "escalate":
            print(f"[iteration {iteration}] Escalate called → handing to supervisor")
            final_reply = ""
            break

        # ── Follow-up action required ──────────────────────────────────────────
        if "next_action" in result:
            contents.append({
                "role": "user",
                "parts": [{"text": result["next_action"]}]
            })
            final_reply = result.get("reply", final_reply)
            continue

        if tool_name == "reply_only":
            final_reply = result.get("reply", final_reply)
            break

        final_reply = result.get("reply", final_reply)

    return final_reply, stage


def _parse_function_args(function_call) -> dict:
    result = {}
    for key, value in function_call.args.items():
        result[key] = _parse_proto_value(value)
    return result


def _parse_proto_value(value):
    if hasattr(value, "items") and not isinstance(value, dict):
        result = {}
        for k, v in value.items():
            key = "qty" if k == "quantity" else k
            result[key] = _parse_proto_value(v)
        return result
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes, dict)):
        return [_parse_proto_value(v) for v in value]
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


def _schema_to_proto(prop: dict):
    type_map = {
        "string":  genai.protos.Type.STRING,
        "integer": genai.protos.Type.INTEGER,
        "number":  genai.protos.Type.NUMBER,
        "boolean": genai.protos.Type.BOOLEAN,
        "array":   genai.protos.Type.ARRAY,
        "object":  genai.protos.Type.OBJECT,
    }
    t = type_map.get(prop.get("type", "string"), genai.protos.Type.STRING)
    kwargs = {"type": t}
    if "enum"        in prop: kwargs["enum"]        = prop["enum"]
    if "description" in prop: kwargs["description"] = prop["description"]
    if t == genai.protos.Type.ARRAY and "items" in prop:
        kwargs["items"] = _schema_to_proto(prop["items"])
    return genai.protos.Schema(**kwargs)