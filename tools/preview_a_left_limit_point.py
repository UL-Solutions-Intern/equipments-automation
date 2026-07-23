import time
import pyautogui
import win32gui

GA_ROOT = 2

A_LEFT_LIMIT_REL = (0.273, 0.584)

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
print("Preview A left limit point")
print("=" * 70)
print()
print("Within 5 seconds, move mouse over Universal Viewer MAIN window.")
print("Do NOT put mouse over cursor value window, VS Code, or PowerShell.")
print("No click will be performed.")
print()

for sec in range(5, 0, -1):
    x, y = pyautogui.position()
    print(f"{sec} sec left | mouse=({x}, {y})", end="\r")
    time.sleep(1)
print()

hwnd, title, rect, mouse_pos = get_window_under_mouse_root()
left, top, right, bottom = rect
width = right - left
height = bottom - top

print()
print("Captured window:")
print(f"title={title}")
print(f"rect={rect}")
print(f"mouse={mouse_pos}")
print()

if "커서값" in title:
    raise RuntimeError("Wrong window: cursor value window was captured.")

if "Visual Studio Code" in title or "PowerShell" in title:
    raise RuntimeError("Wrong window: VS Code or PowerShell was captured.")

a_x = int(left + width * A_LEFT_LIMIT_REL[0])
a_y = int(top + height * A_LEFT_LIMIT_REL[1])

print(f"a_search_left_limit_rel={A_LEFT_LIMIT_REL}")
print(f"a_search_left_limit_abs=({a_x}, {a_y})")
print()
print("Moving mouse pointer to A left limit point in 2 seconds...")
time.sleep(2)

pyautogui.moveTo(a_x, a_y, duration=0.5)

print("Mouse is now at A left limit point.")
print("Look at the Universal Viewer screen.")
print("Holding position for 5 seconds...")
time.sleep(5)

print("Preview completed. No click or drag was performed.")
