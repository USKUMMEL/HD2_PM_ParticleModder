import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control
    implicitHeight: 32
    color: Theme.text
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    placeholderTextColor: Theme.textMuted
    font.pixelSize: 13
    leftPadding: 9
    rightPadding: 9
    selectByMouse: true

    background: Rectangle {
        radius: 4
        color: Theme.background
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.focus : Theme.border
    }
}

