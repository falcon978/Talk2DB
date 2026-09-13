import os

target_dir = "/Users/r/.gemini/antigravity-ide/brain/2986543f-25f2-44b4-8ac6-7a37b7b859af/scratch/Talk2DB"
search_str = "talk2db"
replace_str = "talk2db"

for root, _, files in os.walk(target_dir):
    for file in files:
        if file.endswith((".py", ".toml", ".md", ".txt", "Dockerfile.api", "Dockerfile.ui", ".env")):
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if search_str in content:
                content = content.replace(search_str, replace_str)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Updated {filepath}")
