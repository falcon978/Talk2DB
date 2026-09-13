import os

filepath = "/Users/r/.gemini/antigravity-ide/brain/2986543f-25f2-44b4-8ac6-7a37b7b859af/scratch/Talk2DB/eval/run_eval.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("assignment_total", "task_total")
content = content.replace("assignment_passed", "task_passed")
content = content.replace("assignment-specified", "task-specified")
content = content.replace("Assignment-level", "Task-level")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated run_eval.py")
