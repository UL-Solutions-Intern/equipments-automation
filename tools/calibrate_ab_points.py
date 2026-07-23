import time
import pyautogui
import win32gui

GA_ROOT = 2

def get_window_under_mouse_root():
    x, y = pyautogui.position()
    hwnd = win32gui.WindowFromPoint((x, y))
    root = win32gui.GetAncestor(hwnd, GA_ROOT)
    if root:
        hwnd = root
    title = win32gui.GetWindowText(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    return hwnd, title, rect, (x, y)

print("=" * 70)
print("AB cursor point calibration")
print("=" * 70)
print()
print("Step 0:")
print("Within 5 seconds, move the mouse over the Universal Viewer MAIN window.")
print("Do NOT put the mouse over the cursor value window.")
print("Do NOT put the mouse over VS Code or PowerShell.")
print("Clicking is not required.")
print()

for sec in range(5, 0, -1):
    x, y = pyautogui.position()
    print(f"Move mouse over Universal Viewer main window: {sec} sec left | mouse=({x}, {y})", end="\r")
    time.sleep(1)
print()

hwnd, title, rect, mouse_pos = get_window_under_mouse_root()
main_left, main_top, main_right, main_bottom = rect
main_width = main_right - main_left
main_height = main_bottom - main_top

print()
print("Captured main window from mouse position:")
print(f"mouse={mouse_pos}")
print(f"title={title}")
print(f"rect={rect}")
print()

if "커서값" in title:
    raise RuntimeError("Wrong window captured: cursor value window. Run again and put mouse over Universal Viewer MAIN window.")

if "Visual Studio Code" in title or "PowerShell" in title:
    raise RuntimeError("Wrong window captured: VS Code or PowerShell. Run again and put mouse over Universal Viewer MAIN window.")

if main_width <= 0 or main_height <= 0:
    raise RuntimeError(f"Invalid main window rectangle: {rect}")

points = [
    ("a_search_left_limit", "Move mouse to just INSIDE the graph start, slightly right of the left graph edge."),
    ("a_search_right_limit", "Move mouse to the RIGHT inside the graph, where A/B difference should be shorter."),
    ("b_release_overshoot_target", "Move mouse slightly RIGHT of the graph end point, where B mouseUp should happen."),
]

results = []

print("=" * 70)
print("Do NOT click during point capture.")
print("Just move the mouse to the requested point.")
print("Each point waits 10 seconds.")
print("=" * 70)
print()

for name, desc in points:
    print()
    print("-" * 70)
    print(name)
    print(desc)
    print()

    for sec in range(10, 0, -1):
        x, y = pyautogui.position()
        print(f"{sec} sec left | current mouse=({x}, {y})", end="\r")
        time.sleep(1)
    print()

    x, y = pyautogui.position()
    rel_x = (x - main_left) / main_width
    rel_y = (y - main_top) / main_height

    results.append((name, x, y, rel_x, rel_y))

    print(f"{name}_abs=({x}, {y})")
    print(f"{name}_rel=({rel_x:.3f}, {rel_y:.3f})")

print()
print("=" * 70)
print("COPY THESE VALUES:")
for name, x, y, rel_x, rel_y in results:
    print(f"{name}_rel=({rel_x:.3f}, {rel_y:.3f})")
print("=" * 70)
