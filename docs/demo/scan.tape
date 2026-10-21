# VHS script for the terminal demo: https://github.com/charmbracelet/vhs
# Run from the repository root after building the demo project:
#   python docs/demo/make_demo_project.py ~/deviant-demo
#   vhs docs/demo/scan.tape

Output docs/assets/demo-scan.gif

Set Shell "bash"
Set FontSize 20
Set Width 1200
Set Height 560
Set Theme "Dracula"
Set TypingSpeed 45ms
Set Padding 24

Hide
Type "cd ~/deviant-demo && clear"
Enter
Show

Type "deviant-scan . --with-git"
Sleep 400ms
Enter
Sleep 4s
