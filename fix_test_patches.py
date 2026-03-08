import re
with open("tests/unit/test_search_router.py", "r") as f:
    content = f.read()
new_content = re.sub(r'patch\("application\.search_service', r'patch("application.services.search_service', content)
with open("tests/unit/test_search_router.py", "w") as f:
    f.write(new_content)
