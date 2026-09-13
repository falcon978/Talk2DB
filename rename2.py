import os

target_dir = "/Users/r/.gemini/antigravity-ide/brain/2986543f-25f2-44b4-8ac6-7a37b7b859af/scratch/Talk2DB"

replacements = {
    "target_pool": "target_pool",
    "DB_DSN_TARGET": "DB_DSN_TARGET",
    "Talk2DB": "Talk2DB",
    "Talk2DB": "Talk2DB",
    "talk2db": "talk2db",
    "targetdb": "targetdb",
    "Target DB Pool": "Target DB Pool"
}

for root, _, files in os.walk(target_dir):
    for file in files:
        if file.endswith((".py", ".toml", ".md", ".txt", "Dockerfile.api", "Dockerfile.ui", ".env", ".yml")):
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            modified = False
            for k, v in replacements.items():
                if k in content:
                    content = content.replace(k, v)
                    modified = True
            
            if modified:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Updated {filepath}")
