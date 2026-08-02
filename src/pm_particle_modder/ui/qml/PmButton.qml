import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control
    property bool accent: false
    property string tooltip: ""
    implicitHeight: 34
    implicitWidth: Math.max(72, contentItem.implicitWidth + 24)
    leftPadding: 12
    rightPadding: 12
    hoverEnabled: true

    contentItem: Text {
        text: control.text
        color: !control.enabled ? Theme.textMuted
              : control.accent ? Theme.accentText : Theme.text
        font.pixelSize: 13
        font.weight: control.accent ? Font.DemiBold : Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 5
        color: !control.enabled ? Theme.surface
             : control.accent ? (control.down ? Theme.accentStrong : Theme.accent)
             : control.down ? Theme.surfaceHover
             : control.hovered ? Theme.surfaceHover : Theme.surfaceRaised
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? Theme.focus
                    : control.accent ? Theme.accentStrong : Theme.border
    }

    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.text: tooltip
    ToolTip.delay: 500
}

