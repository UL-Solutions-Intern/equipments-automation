import time
import pyautogui
import win32gui

GA_ROOT = 2

B_RELEASE_REL = (0.721, 0.564)

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
print("Preview B release point")
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

b_x = int(left + width * B_RELEASE_REL[0])
b_y = int(top + height * B_RELEASE_REL[1])

print(f"b_release_rel={B_RELEASE_REL}")
print(f"b_release_abs=({b_x}, {b_y})")
print()
print("Moving mouse pointer to B release point in 2 seconds...")
time.sleep(2)

pyautogui.moveTo(b_x, b_y, duration=0.5)

print("Mouse is now at B release point.")
print("Look at the Universal Viewer screen.")
print("Holding position for 5 seconds...")
time.sleep(5)

print("Preview completed. No click or drag was performed.")
