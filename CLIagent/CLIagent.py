
import json
import os
import subprocess
import sys
import ollama

llm = "qwen2.5"

# 1. Define the actual tool function
def execute_shell_command(command: str) -> str:
    """Executes a terminal command and returns stdout or stderr."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return str(e)

# 2. Map tool names to Python functions
TOOL_MAP = {
    'execute_shell_command': execute_shell_command
}

# 3. Provide schema representations for Ollama
TOOLS_SCHEMA = [
    {
        'type': 'function',
        'function': {
            'name': 'execute_shell_command',
            'description': 'Execute safe terminal shell commands on the local machine.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'description': 'The exact bash or shell command to run.',
                    }
                },
                'required': ['command'],
            },
        },
    }
]       


def run_agent_loop():
    print("🤖 Local Ollama CLI Agent Initialized. Type 'exit' to quit.\n")
    
    # Maintain continuous conversation history
    messages = [
        {"role": "system", "content": "You are a helpful local CLI assistant. You can inspect the system and run tasks using your tools."}
    ]

    while True:
        try:
            user_input = input("✨ User: ")
            if user_input.lower() in ['exit', 'quit']:
                break
            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})
            
            # Request completion from Ollama with enabled tools
            response = ollama.chat(
                model=llm,
                messages=messages,
                tools=TOOLS_SCHEMA
            )
            
            # Process potential tool calls requested by the model
            while response.get('message', {}).get('tool_calls'):
                messages.append(response['message'])
                
                for tool_call in response['message']['tool_calls']:
                    tool_name = tool_call['function']['name']
                    arguments = tool_call['function']['arguments']
                    
                    print(f"🛠️ [Executing Tool] {tool_name}({json.dumps(arguments)})")
                    
                    if tool_name in TOOL_MAP:
                        # Execute tool and grab output string
                        tool_result = TOOL_MAP[tool_name](**arguments)
                        
                        # Provide tool outcome back to the model context
                        messages.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result
                        })
                    else:
                        print(f"❌ Unknown tool execution attempted: {tool_name}")
                
                # Re-submit history including tool logs for final evaluation
                response = ollama.chat(
                    model=llm,
                    messages=messages,
                    tools=TOOLS_SCHEMA
                )

            # Display final text answer to user
            agent_reply = response['message']['content']
            print(f"🤖 Agent: {agent_reply}\n")
            messages.append({"role": "assistant", "content": agent_reply})

        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)

if __name__ == '__main__':
    run_agent_loop()