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
print("B release point calibration")
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

print("=" * 70)
print("B release point")
print("Move mouse to slightly RIGHT of the graph end point.")
print("This is where mouseUp should happen so B lands at the final endpoint.")
print("Do NOT click. Just move the mouse.")
print("=" * 70)
print()

for sec in range(10, 0, -1):
    x, y = pyautogui.position()
    print(f"{sec} sec left | current mouse=({x}, {y})", end="\r")
    time.sleep(1)
print()

x, y = pyautogui.position()
rel_x = (x - main_left) / main_width
rel_y = (y - main_top) / main_height

print()
print("=" * 70)
print("COPY THIS VALUE:")
print(f"b_release_overshoot_target_abs=({x}, {y})")
print(f"b_release_overshoot_target_rel=({rel_x:.3f}, {rel_y:.3f})")
print("=" * 70)
