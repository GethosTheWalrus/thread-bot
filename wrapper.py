import re

with open('backend/app/workflows/thread_workflow.py', 'r') as f:
    content = f.read()

# We want to wrap everything starting from:
#         # ── Get chat history ─────────────────────────────────────────
# all the way to the end of the run method, before the final return.

parts = content.split("        # ── Get chat history ─────────────────────────────────────────")

header = parts[0]
body = "        # ── Get chat history ─────────────────────────────────────────" + parts[1]

# Indent the body by 4 spaces
lines = body.split("\n")
indented_body = []
for line in lines:
    if line.strip():
        indented_body.append("    " + line)
    else:
        indented_body.append(line)

new_body = "\n".join(indented_body)

try_except = f"""        try:
{new_body}
        except Exception as e:
            await execute_activity(
                publish_error,
                {{
                    "redis_url": llm_config.get("redis_url"),
                    "stream_channel": llm_config.get("stream_channel"),
                    "thread_id": thread_id,
                    "error": str(e),
                }},
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            raise e
"""

with open('backend/app/workflows/thread_workflow.py', 'w') as f:
    f.write(header + try_except)

