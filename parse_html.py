lines = open('static/style.css', 'r', encoding='utf-8').readlines()
for i, l in enumerate(lines):
    if 'dashboard' in l.lower() or 'grid' in l.lower():
        print(f"{i+1}: {l.strip()}")
