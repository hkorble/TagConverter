import re

with open("web_static/index.html", "r", encoding="utf-8") as f:
    content = f.read()

onclicks = set()
for match in re.finditer(r'onclick="([^"]+)"', content):
    call = match.group(1).strip()
    if call.startswith("document."):
        continue
    fn = call.split("(")[0].strip()
    onclicks.add(fn)

fns = set(re.findall(r'function\s+([a-zA-Z0-9_]+)\s*\(', content))

print("Onclick handlers in HTML:", sorted(list(onclicks)))
print("Defined functions:", sorted(list(fns)))

missing = onclicks - fns
print("Missing functions:", missing)
assert len(missing) == 0, f"Missing functions: {missing}"
print("All onclick functions successfully matched!")
