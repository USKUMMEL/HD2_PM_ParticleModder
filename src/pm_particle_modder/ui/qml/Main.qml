pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1180
    height: 760
    minimumWidth: 880
    minimumHeight: 600
    visible: true
    color: Theme.background
    title: controller.hasDocument
           ? controller.currentTitle + " - PM ParticleModder"
           : "PM ParticleModder"
    property int sectionIndex: 0
    property bool sidePanelExpanded: true
    property var selectedParticleIndexes: []
    property int particleSelectionAnchor: -1
    property var collapsedParticleGroups: []

    function particleIsSelected(index) {
        return selectedParticleIndexes.indexOf(index) >= 0
    }

    function clearParticleSelection() {
        selectedParticleIndexes = []
        particleSelectionAnchor = -1
    }

    function selectParticle(index, modifiers) {
        const useRange = (modifiers & Qt.ShiftModifier) !== 0 && particleSelectionAnchor >= 0
        const toggle = (modifiers & Qt.ControlModifier) !== 0
        let nextSelection = []
        if (useRange) {
            const first = Math.min(particleSelectionAnchor, index)
            const last = Math.max(particleSelectionAnchor, index)
            for (let item = first; item <= last; ++item)
                nextSelection.push(item)
        } else if (toggle) {
            nextSelection = selectedParticleIndexes.slice()
            const selectedIndex = nextSelection.indexOf(index)
            if (selectedIndex >= 0)
                nextSelection.splice(selectedIndex, 1)
            else
                nextSelection.push(index)
            particleSelectionAnchor = index
        } else {
            nextSelection = [index]
            particleSelectionAnchor = index
        }
        selectedParticleIndexes = nextSelection
    }

    function selectParticleForContext(index) {
        if (!particleIsSelected(index)) {
            selectedParticleIndexes = [index]
            particleSelectionAnchor = index
        }
    }

    function isParticleGroupCollapsed(group) {
        return collapsedParticleGroups.indexOf(group) >= 0
    }

    function toggleParticleGroup(group) {
        const nextCollapsedGroups = collapsedParticleGroups.slice()
        const groupIndex = nextCollapsedGroups.indexOf(group)
        if (groupIndex >= 0)
            nextCollapsedGroups.splice(groupIndex, 1)
        else
            nextCollapsedGroups.push(group)
        collapsedParticleGroups = nextCollapsedGroups
    }

    onClosing: function(close) {
        close.accepted = controller.requestExit()
    }

    Shortcut { sequence: StandardKey.Open; onActivated: controller.openFiles() }
    Shortcut { sequence: StandardKey.Save; enabled: controller.documentCount > 0; onActivated: controller.saveProject() }
    Shortcut { sequence: StandardKey.SaveAs; enabled: controller.documentCount > 0; onActivated: controller.saveProjectAs() }
    Shortcut { sequence: StandardKey.Undo; enabled: controller.canUndo; onActivated: controller.undo() }
    Shortcut { sequence: StandardKey.Redo; enabled: controller.canRedo; onActivated: controller.redo() }

    header: Rectangle {
        height: 54
        color: Theme.surface
        border.width: 0

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 8

            Rectangle {
                id: fileMenuButton
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                radius: 4
                color: fileMenuMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceRaised
                border.width: 1
                border.color: Theme.border
                Canvas {
                    anchors.centerIn: parent
                    width: 16
                    height: 16
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        ctx.strokeStyle = Theme.text
                        ctx.lineWidth = 1.4
                        ctx.strokeRect(3.5, 2.5, 8, 11)
                        ctx.beginPath()
                        ctx.moveTo(5.5, 5.5)
                        ctx.lineTo(9.5, 5.5)
                        ctx.moveTo(5.5, 8.5)
                        ctx.lineTo(11, 8.5)
                        ctx.moveTo(5.5, 11.5)
                        ctx.lineTo(11, 11.5)
                        ctx.stroke()
                    }
                }
                MouseArea {
                    id: fileMenuMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: fileMenu.popup(fileMenuButton, 0, fileMenuButton.height)
                }
                ToolTip.visible: fileMenuMouse.containsMouse
                ToolTip.text: "File"
                ToolTip.delay: 500
            }
            PmButton { text: "Load Archive"; tooltip: "Load an archive by ID or found archive name"; onClicked: window.sectionIndex = 6 }
            PmButton { text: "Create Patch"; tooltip: "Create a patch target"; onClicked: controller.createPatch() }
            Rectangle {
                id: patchSelector
                Layout.preferredWidth: 170
                Layout.preferredHeight: 34
                radius: 5
                color: patchSelectorMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceRaised
                border.width: 1
                border.color: Theme.border
                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 10
                    anchors.rightMargin: 24
                    text: controller.selectedPatchName
                    color: controller.hasSelectedPatch ? Theme.text : Theme.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: "v"
                    color: Theme.textMuted
                    font.pixelSize: 11
                }
                MouseArea {
                    id: patchSelectorMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: patchMenu.popup(patchSelector, 0, patchSelector.height)
                    onDoubleClicked: controller.renameSelectedPatch()
                }
                ToolTip.visible: patchSelectorMouse.containsMouse
                ToolTip.text: controller.hasSelectedPatch ? "Click to select, double-click to rename" : "Select a patch target"
                ToolTip.delay: 500
            }
            PmButton { text: "Write Patch"; enabled: controller.canWritePatch && controller.hasSelectedPatch; tooltip: "Write the selected patch"; onClicked: controller.writePatch() }
            Item { Layout.fillWidth: true }
        }

        Menu {
            id: fileMenu
            MenuItem { text: "Select Helldivers 2 Data Folder"; onTriggered: controller.selectGameDataDirectory() }
            MenuSeparator {}
            MenuItem { text: "Open Project"; onTriggered: controller.openProject() }
            MenuItem { text: "Save Project"; enabled: controller.documentCount > 0; onTriggered: controller.saveProjectAs() }
            MenuItem { text: "Save"; enabled: controller.documentCount > 0; onTriggered: controller.saveProject() }
            MenuSeparator {}
            MenuItem { text: "Open Particle"; onTriggered: controller.openFiles() }
            MenuItem { text: "Save Particle"; enabled: controller.canSaveParticle; onTriggered: controller.saveParticle() }
            MenuItem { text: "Save Particle As"; enabled: controller.canSaveParticle; onTriggered: controller.saveCurrentAs() }
            MenuItem { text: "Save Patch"; enabled: controller.canWritePatch; onTriggered: controller.writePatch() }
            MenuSeparator {}
            MenuItem { text: "About"; onTriggered: aboutDialog.open() }
        }

        Menu {
            id: patchMenu
            Instantiator {
                model: controller.patchOptions
                delegate: MenuItem {
                    required property int index
                    required property string modelData
                    text: modelData
                    onTriggered: controller.selectPatch(index)
                }
                onObjectAdded: function(index, object) { patchMenu.insertItem(index, object) }
                onObjectRemoved: function(_index, object) { patchMenu.removeItem(object) }
            }
            MenuItem { visible: controller.patchOptions.length === 0; enabled: false; text: "No patch targets" }
        }
    }

    Dialog {
        id: aboutDialog
        title: "About PM ParticleModder"
        modal: true
        standardButtons: Dialog.Ok
        anchors.centerIn: parent
        width: 390
        contentItem: Text {
            text: "Tool Dev : Uskummel\nHuge thank to Hd2 modding community\nSpecial thanks to Box, Eve and other Dev of Hd2 Sdk"
            color: Theme.text
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            padding: 18
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.preferredWidth: window.sidePanelExpanded ? 292 : 46
                Layout.fillHeight: true
                color: Theme.surface

                ColumnLayout {
                    visible: window.sidePanelExpanded
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 5

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 28
                        Text {
                            text: "OPEN PARTICLES  " + controller.documentCount
                                  + (window.selectedParticleIndexes.length > 0
                                     ? " / " + window.selectedParticleIndexes.length + " SELECTED" : "")
                            color: Theme.textMuted
                            font.pixelSize: 10
                            font.weight: Font.DemiBold
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            objectName: "sidebarCollapse"
                            Layout.preferredWidth: 28
                            Layout.preferredHeight: 28
                            radius: 4
                            color: collapseMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceRaised
                            border.width: 1
                            border.color: Theme.border
                            Text { anchors.centerIn: parent; text: "<<"; color: Theme.textMuted; font.pixelSize: 11 }
                            MouseArea {
                                id: collapseMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: window.sidePanelExpanded = false
                            }
                            ToolTip.visible: collapseMouse.containsMouse
                            ToolTip.text: "Collapse sidebar"
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 158
                        color: Theme.background
                        border.width: 1
                        border.color: Theme.border
                        radius: 5
                        clip: true

                        ListView {
                            id: openParticlesList
                            objectName: "openParticlesList"
                            anchors.fill: parent
                            anchors.margins: 4
                            model: documentsModel
                            spacing: 3
                            section.property: "group"
                            section.criteria: ViewSection.FullString
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            section.delegate: Rectangle {
                                id: groupHeader
                                required property string section
                                width: openParticlesList.width - 8
                                height: 25
                                color: "transparent"
                                Text {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.leftMargin: 5
                                    anchors.rightMargin: 5
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (window.isParticleGroupCollapsed(groupHeader.section) ? "[+] " : "[-] ")
                                          + groupHeader.section.toUpperCase()
                                    color: Theme.accent
                                    font.pixelSize: 10
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: function(mouse) {
                                        if (mouse.button === Qt.RightButton) {
                                            groupContextMenu.targetGroup = groupHeader.section
                                            groupContextMenu.popup()
                                        } else {
                                            window.toggleParticleGroup(groupHeader.section)
                                        }
                                    }
                                }
                            }

                            delegate: Rectangle {
                                id: particleDelegate
                                objectName: "openParticle-" + index
                                required property int index
                                required property string title
                                required property bool dirty
                                required property string filePath
                                required property string group
                                required property bool archiveBacked
                                required property bool patchIncluded
                                required property bool applyIncluded
                                required property bool resettable
                                width: openParticlesList.width - 8
                                visible: !window.isParticleGroupCollapsed(group)
                                height: visible ? 34 : 0
                                radius: 4
                                color: window.particleIsSelected(index) ? "#40594A"
                                     : controller.currentIndex === index ? Theme.surfaceRaised
                                     : particleMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                border.width: window.particleIsSelected(index)
                                              || controller.currentIndex === index ? 1 : 0
                                border.color: window.particleIsSelected(index) ? Theme.accent : Theme.borderStrong

                                Text {
                                    anchors.left: particleApply.right
                                    anchors.right: particlePatch.left
                                    anchors.leftMargin: 4
                                    anchors.rightMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: particleDelegate.title + (particleDelegate.dirty ? " *" : "")
                                    color: window.particleIsSelected(particleDelegate.index)
                                           || controller.currentIndex === particleDelegate.index ? Theme.text : Theme.textMuted
                                    font.pixelSize: 11
                                    elide: Text.ElideMiddle
                                }
                                Rectangle {
                                    id: particleApply
                                    width: 22
                                    height: 22
                                    anchors.left: parent.left
                                    anchors.leftMargin: 3
                                    anchors.verticalCenter: parent.verticalCenter
                                    radius: 3
                                    color: particleApplyMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                    Canvas {
                                        anchors.centerIn: parent
                                        width: 15
                                        height: 15
                                        property bool included: particleDelegate.applyIncluded
                                        onIncludedChanged: requestPaint()
                                        onPaint: {
                                            const ctx = getContext("2d")
                                            ctx.clearRect(0, 0, width, height)
                                            ctx.lineWidth = 1.5
                                            ctx.strokeStyle = included ? Theme.accent : Theme.textMuted
                                            ctx.strokeRect(2, 2, 11, 11)
                                            if (included) {
                                                ctx.beginPath()
                                                ctx.moveTo(4, 7.5)
                                                ctx.lineTo(6.5, 10)
                                                ctx.lineTo(11.5, 4.8)
                                                ctx.stroke()
                                            }
                                        }
                                    }
                                    MouseArea {
                                        id: particleApplyMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: controller.toggleApplyInclude(particleDelegate.index)
                                    }
                                    ToolTip.visible: particleApplyMouse.containsMouse
                                    ToolTip.text: particleDelegate.applyIncluded
                                                  ? "Apply target enabled" : "Enable as an apply target"
                                    ToolTip.delay: 500
                                }
                                Rectangle {
                                    id: particleReset
                                    width: particleDelegate.resettable ? 24 : 0
                                    height: 24
                                    anchors.right: parent.right
                                    anchors.rightMargin: 3
                                    anchors.verticalCenter: parent.verticalCenter
                                    radius: 3
                                    visible: width > 0
                                    color: particleResetMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                    Canvas {
                                        anchors.centerIn: parent
                                        width: 16
                                        height: 16
                                        onPaint: {
                                            const ctx = getContext("2d")
                                            ctx.clearRect(0, 0, width, height)
                                            ctx.strokeStyle = Theme.textMuted
                                            ctx.lineWidth = 1.5
                                            ctx.strokeRect(4, 5, 8, 9)
                                            ctx.beginPath()
                                            ctx.moveTo(3, 4)
                                            ctx.lineTo(13, 4)
                                            ctx.moveTo(6, 2.5)
                                            ctx.lineTo(10, 2.5)
                                            ctx.moveTo(6.5, 7)
                                            ctx.lineTo(6.5, 12)
                                            ctx.moveTo(9.5, 7)
                                            ctx.lineTo(9.5, 12)
                                            ctx.stroke()
                                        }
                                    }
                                    MouseArea {
                                        id: particleResetMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: controller.resetDocument(particleDelegate.index)
                                    }
                                    ToolTip.visible: particleResetMouse.containsMouse
                                    ToolTip.text: "Reset particle to opened source data"
                                    ToolTip.delay: 500
                                }
                                Rectangle {
                                    id: particlePatch
                                    width: 24
                                    height: 24
                                    anchors.right: particleReset.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    radius: 3
                                    color: particlePatchMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                    Canvas {
                                        anchors.centerIn: parent
                                        width: 16
                                        height: 16
                                        property bool included: particleDelegate.patchIncluded
                                        onIncludedChanged: requestPaint()
                                        onPaint: {
                                            const ctx = getContext("2d")
                                            ctx.clearRect(0, 0, width, height)
                                            ctx.fillStyle = included ? Theme.accent : "transparent"
                                            ctx.strokeStyle = included ? Theme.accent : Theme.textMuted
                                            ctx.lineWidth = 1.5
                                            ctx.beginPath()
                                            ctx.moveTo(8, 2)
                                            ctx.lineTo(13, 4.5)
                                            ctx.lineTo(12, 10.5)
                                            ctx.quadraticCurveTo(10.5, 13.5, 8, 15)
                                            ctx.quadraticCurveTo(5.5, 13.5, 4, 10.5)
                                            ctx.lineTo(3, 4.5)
                                            ctx.closePath()
                                            ctx.fill()
                                            ctx.stroke()
                                        }
                                    }
                                    MouseArea {
                                        id: particlePatchMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: controller.togglePatchInclude(particleDelegate.index)
                                    }
                                    ToolTip.visible: particlePatchMouse.containsMouse
                                    ToolTip.text: particleDelegate.patchIncluded ? "Included in patch" : "Include particle in patch"
                                    ToolTip.delay: 500
                                }
                                MouseArea {
                                    id: particleMouse
                                    anchors.left: particleApply.right
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    anchors.right: particlePatch.left
                                    hoverEnabled: true
                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: function(mouse) {
                                        if (mouse.button === Qt.RightButton) {
                                            if ((mouse.modifiers & (Qt.ShiftModifier | Qt.ControlModifier)) !== 0)
                                                window.selectParticle(particleDelegate.index, mouse.modifiers)
                                            else
                                                window.selectParticleForContext(particleDelegate.index)
                                            fileContextMenu.targetIndexes = window.selectedParticleIndexes
                                            fileContextMenu.popup()
                                        } else {
                                            window.selectParticle(particleDelegate.index, mouse.modifiers)
                                            controller.setCurrentDocument(particleDelegate.index)
                                        }
                                    }
                                }
                                ToolTip.visible: particleMouse.containsMouse
                                ToolTip.text: particleDelegate.filePath
                                ToolTip.delay: 500
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: controller.documentCount === 0
                            text: "No particle files open"
                            color: Theme.textMuted
                            font.pixelSize: 11
                        }
                    }
                    PmButton {
                        Layout.fillWidth: true
                        text: "Open Particle"
                        accent: true
                        tooltip: "Open particle files"
                        onClicked: controller.openFiles()
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    Text {
                        Layout.fillWidth: true
                        text: "EDITOR"
                        color: Theme.textMuted
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }
                    Repeater {
                        model: ["Color", "Opacity", "Intensity", "Lifetime", "Visualizers", "Texture"]
                        delegate: Rectangle {
                            id: navItem
                            required property int index
                            required property string modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 38
                            radius: 5
                            color: window.sectionIndex === index ? Theme.surfaceRaised
                                 : navMouse.containsMouse ? Theme.surfaceHover : "transparent"
                            border.width: window.sectionIndex === index ? 1 : 0
                            border.color: Theme.borderStrong
                            Rectangle {
                                width: 3
                                height: 20
                                radius: 1
                                anchors.left: parent.left
                                anchors.leftMargin: 3
                                anchors.verticalCenter: parent.verticalCenter
                                color: window.sectionIndex === navItem.index ? Theme.accent : "transparent"
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 16
                                anchors.verticalCenter: parent.verticalCenter
                                text: navItem.modelData
                                color: window.sectionIndex === navItem.index ? Theme.text : Theme.textMuted
                                font.pixelSize: 13
                                font.weight: window.sectionIndex === navItem.index ? Font.DemiBold : Font.Normal
                            }
                            MouseArea {
                                id: navMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: window.sectionIndex = navItem.index
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            Layout.fillWidth: true
                            text: controller.hasDocument ? "PARTICLE  " + controller.versionText : "NO DOCUMENT"
                            color: Theme.textMuted
                            font.pixelSize: 10
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "PM ParticleModder Version " + controller.applicationVersion
                            color: Theme.textMuted
                            font.pixelSize: 9
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                        }
                    }
                }

                Rectangle {
                    visible: !window.sidePanelExpanded
                    anchors.fill: parent
                    color: Theme.surface
                    Text {
                        anchors.centerIn: parent
                        text: ">>"
                        color: Theme.textMuted
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: collapsedPanelMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: window.sidePanelExpanded = true
                    }
                    ToolTip.visible: collapsedPanelMouse.containsMouse
                    ToolTip.text: "Expand sidebar"
                }

                Menu {
                    id: fileContextMenu
                    objectName: "fileContextMenu"
                    property var targetIndexes: []
                    MenuItem {
                        text: "Create group..."
                        enabled: fileContextMenu.targetIndexes.length > 0
                        onTriggered: {
                            controller.createGroup(fileContextMenu.targetIndexes)
                            window.clearParticleSelection()
                        }
                    }
                    Menu {
                        id: addToGroupMenu
                        title: "Add to group"
                        enabled: fileContextMenu.targetIndexes.length > 0 && controller.groupNames.length > 0
                        Instantiator {
                            model: controller.groupNames
                            delegate: MenuItem {
                                required property string modelData
                                text: modelData
                                onTriggered: {
                                    controller.addDocumentsToGroup(fileContextMenu.targetIndexes, modelData)
                                    window.clearParticleSelection()
                                }
                            }
                            onObjectAdded: function(index, object) { addToGroupMenu.insertItem(index, object) }
                            onObjectRemoved: function(_index, object) { addToGroupMenu.removeItem(object) }
                        }
                    }
                    MenuItem {
                        text: "Remove selected from group"
                        enabled: fileContextMenu.targetIndexes.length > 0
                        onTriggered: {
                            controller.removeDocumentsFromGroup(fileContextMenu.targetIndexes)
                            window.clearParticleSelection()
                        }
                    }
                    MenuSeparator { }
                    MenuItem {
                        text: "Delete selected from PM"
                        enabled: fileContextMenu.targetIndexes.length > 0
                        onTriggered: {
                            controller.closeDocuments(fileContextMenu.targetIndexes)
                            window.clearParticleSelection()
                        }
                    }
                }

                Menu {
                    id: groupContextMenu
                    property string targetGroup: ""
                    MenuItem {
                        text: "Rename group..."
                        enabled: groupContextMenu.targetGroup !== "Ungrouped"
                        onTriggered: controller.renameGroup(groupContextMenu.targetGroup)
                    }
                    MenuItem {
                        text: "Ungroup all files"
                        enabled: groupContextMenu.targetGroup !== "Ungrouped"
                        onTriggered: controller.ungroupGroup(groupContextMenu.targetGroup)
                    }
                }
            }

            Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: Theme.border }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.background

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: controller.hasDocument ? 58 : 0
                        visible: height > 0
                        color: Theme.background
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 18
                            anchors.rightMargin: 18
                            spacing: 12
                            Text {
                                text: controller.currentTitle
                                color: Theme.text
                                font.pixelSize: 15
                                font.weight: Font.DemiBold
                                elide: Text.ElideMiddle
                                Layout.maximumWidth: 320
                            }
                            Text {
                                Layout.fillWidth: true
                                text: controller.currentPath
                                color: Theme.textMuted
                                font.pixelSize: 11
                                elide: Text.ElideMiddle
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: controller.hasDocument ? 1 : 0; color: Theme.border }

                    StackLayout {
                        objectName: "editorStack"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: controller.hasDocument || window.sectionIndex === 6
                                      ? window.sectionIndex : 7

                        GraphTable {
                            objectName: "colorGraphTable"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            tableModel: colorModel
                            kind: "color"
                            colorMode: true
                        }
                        GraphTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            tableModel: opacityModel
                            kind: "opacity"
                        }
                        GraphTable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            tableModel: intensityModel
                            kind: "intensity"
                        }

                        Item {
                            ColumnLayout {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.margins: 18
                                width: Math.min(540, parent.width - 36)
                                spacing: 12
                                Text { text: "Particle Lifetime"; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 112
                                    radius: 6
                                    color: Theme.surface
                                    border.width: 1
                                    border.color: Theme.border
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 16
                                        spacing: 12
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Text { text: "Minimum"; color: Theme.textMuted; font.pixelSize: 11 }
                                            PmTextField {
                                                Layout.fillWidth: true
                                                text: controller.lifetimeMin.toString()
                                                validator: DoubleValidator { notation: DoubleValidator.StandardNotation }
                                                onEditingFinished: controller.setLifetime("min", text)
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            Text { text: "Maximum"; color: Theme.textMuted; font.pixelSize: 11 }
                                            PmTextField {
                                                Layout.fillWidth: true
                                                text: controller.lifetimeMax.toString()
                                                validator: DoubleValidator { notation: DoubleValidator.StandardNotation }
                                                onEditingFinished: controller.setLifetime("max", text)
                                            }
                                        }
                                        Text { text: "seconds"; color: Theme.textMuted; font.pixelSize: 12; Layout.alignment: Qt.AlignBottom; Layout.bottomMargin: 8 }
                                    }
                                }
                                Item { Layout.fillHeight: true }
                            }
                        }

                        Item {
                            ListView {
                                id: visualizerList
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                clip: true
                                model: visualizerModel
                                boundsBehavior: Flickable.StopAtBounds
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                delegate: Rectangle {
                                    id: visualizerDelegate
                                    required property int index
                                    required property string systemLabel
                                    required property string visualizerType
                                    required property string materialId
                                    required property string unitId
                                    required property string meshId
                                    required property bool hasMaterial
                                    required property bool hasUnit
                                    required property bool hasMesh
                                    required property bool systemEnabled
                                    required property int systemIndex
                                    width: visualizerList.width - 12
                                    height: 74 + (hasMaterial ? 54 : 0) + (hasUnit ? 54 : 0) + (hasMesh ? 54 : 0)
                                    radius: 6
                                    color: systemEnabled ? Theme.surface : Theme.surfaceHover
                                    border.width: 1
                                    border.color: Theme.border
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 14
                                        spacing: 7
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text { text: visualizerDelegate.systemLabel; color: Theme.text; font.pixelSize: 14; font.weight: Font.DemiBold }
                                            Item { Layout.fillWidth: true }
                                            CheckBox {
                                                id: systemEnabledToggle
                                                checked: visualizerDelegate.systemEnabled
                                                text: "Enabled"
                                                onClicked: controller.toggleParticleSystem(visualizerDelegate.systemIndex)
                                            }
                                            Text { text: visualizerDelegate.visualizerType; color: Theme.accent; font.pixelSize: 12 }
                                        }
                                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                                        IdField { visible: visualizerDelegate.hasMaterial; label: "Material ID"; value: visualizerDelegate.materialId; field: "material"; row: visualizerDelegate.index }
                                        IdField { visible: visualizerDelegate.hasUnit; label: "Unit ID"; value: visualizerDelegate.unitId; field: "unit"; row: visualizerDelegate.index }
                                        IdField { visible: visualizerDelegate.hasMesh; label: "Mesh ID"; value: visualizerDelegate.meshId; field: "mesh"; row: visualizerDelegate.index }
                                        Item { Layout.fillHeight: true }
                                    }
                                }
                                Text {
                                    anchors.centerIn: parent
                                    visible: visualizerList.count === 0
                                    text: "No editable visualizers in this particle file"
                                    color: Theme.textMuted
                                    font.pixelSize: 14
                                }
                            }
                        }

                        Item {
                            id: texturePanel
                            property int selectedTextureIndex: -1
                            property bool listView: controller.textureListView
                            property bool compareTexture: false
                            Connections {
                                target: controller
                                function onStateChanged() {
                                    if (!controller.hasTextureReplacement)
                                        texturePanel.compareTexture = false
                                }
                            }
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 10
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text { text: "TEXTURE"; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                    Rectangle {
                                        Layout.preferredWidth: 122
                                        Layout.preferredHeight: 29
                                        radius: 4
                                        color: Theme.surface
                                        border.color: Theme.border
                                        Row {
                                            anchors.fill: parent
                                            anchors.margins: 2
                                            Repeater {
                                                model: ["Viewer", "List"]
                                                delegate: Rectangle {
                                                    required property int index
                                                    required property string modelData
                                                    width: 58
                                                    height: parent.height
                                                    radius: 3
                                                    color: (texturePanel.listView === (index === 1)) ? Theme.surfaceRaised : "transparent"
                                                    Text { anchors.centerIn: parent; text: modelData; color: (texturePanel.listView === (index === 1)) ? Theme.text : Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold }
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        cursorShape: Qt.PointingHandCursor
                                                        onClicked: {
                                                            if (index === 1)
                                                                texturePanel.compareTexture = false
                                                            controller.setTextureListView(index === 1)
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    PmButton { text: "Export PNG"; enabled: controller.hasSelectedTexture; onClicked: controller.exportSelectedTexturePng() }
                                    PmButton { text: "Export DDS"; enabled: controller.hasSelectedTexture; onClicked: controller.exportSelectedTextureDds() }
                                    PmButton { text: "Import PNG"; enabled: controller.hasSelectedTexture; onClicked: controller.importSelectedTexturePng() }
                                    PmButton { text: "Import DDS"; enabled: controller.hasSelectedTexture; onClicked: controller.importSelectedTextureDds() }
                                    PmButton {
                                        visible: !texturePanel.listView && controller.hasTextureReplacement
                                        text: texturePanel.compareTexture ? "Viewer" : "Compare"
                                        onClicked: texturePanel.compareTexture = !texturePanel.compareTexture
                                    }
                                    Rectangle {
                                        Layout.preferredWidth: 30
                                        Layout.preferredHeight: 30
                                        visible: !texturePanel.listView && controller.hasTextureReplacement
                                        radius: 4
                                        color: resetTextureMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceRaised
                                        border.width: 1
                                        border.color: Theme.border
                                        Canvas {
                                            anchors.centerIn: parent
                                            width: 16
                                            height: 16
                                            onPaint: {
                                                const ctx = getContext("2d")
                                                ctx.clearRect(0, 0, width, height)
                                                ctx.strokeStyle = Theme.textMuted
                                                ctx.lineWidth = 1.5
                                                ctx.strokeRect(4, 5, 8, 9)
                                                ctx.beginPath()
                                                ctx.moveTo(3, 4)
                                                ctx.lineTo(13, 4)
                                                ctx.moveTo(6, 2.5)
                                                ctx.lineTo(10, 2.5)
                                                ctx.moveTo(6.5, 7)
                                                ctx.lineTo(6.5, 12)
                                                ctx.moveTo(9.5, 7)
                                                ctx.lineTo(9.5, 12)
                                                ctx.stroke()
                                            }
                                        }
                                        MouseArea {
                                            id: resetTextureMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                texturePanel.compareTexture = false
                                                controller.resetSelectedTexture()
                                            }
                                        }
                                        ToolTip.visible: resetTextureMouse.containsMouse
                                        ToolTip.text: "Reset texture to original data"
                                        ToolTip.delay: 500
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    visible: !texturePanel.listView
                                    Layout.preferredHeight: texturePanel.listView ? 0 : 38
                                    spacing: 10
                                    ComboBox {
                                        id: systemSelector
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: !texturePanel.listView && controller.hasTextureMaterialChoice ? 1 : 2
                                        Layout.preferredHeight: 38
                                        model: controller.textureSystemOptions
                                        enabled: model.length > 0
                                        currentIndex: Math.max(0, controller.textureSystemOptions.indexOf("Particle System " + (controller.selectedTextureSystemIndex + 1)))
                                        onActivated: controller.selectTextureSystem(currentIndex)
                                        contentItem: Text {
                                            leftPadding: 11
                                            rightPadding: 30
                                            text: systemSelector.displayText
                                            color: Theme.text
                                            font.pixelSize: 12
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }
                                        background: Rectangle { radius: 4; color: Theme.surface; border.color: systemSelector.activeFocus ? Theme.focus : Theme.border; border.width: 1 }
                                    }
                                    ComboBox {
                                        id: materialSelector
                                        Layout.fillWidth: true
                                        visible: !texturePanel.listView && controller.hasTextureMaterialChoice
                                        Layout.preferredHeight: 38
                                        model: controller.textureMaterialOptions
                                        enabled: model.length > 0
                                        currentIndex: Math.max(0, controller.textureMaterialOptions.indexOf(controller.selectedTextureMaterialId))
                                        onActivated: controller.selectTextureMaterial(currentIndex)
                                        contentItem: Text {
                                            leftPadding: 11
                                            rightPadding: 30
                                            text: materialSelector.displayText.length > 0 ? "Material " + materialSelector.displayText : "No material"
                                            color: Theme.text
                                            font.pixelSize: 12
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideMiddle
                                        }
                                        background: Rectangle { radius: 4; color: Theme.surface; border.color: materialSelector.activeFocus ? Theme.focus : Theme.border; border.width: 1 }
                                    }
                                }
                                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    visible: !texturePanel.listView
                                    color: Theme.surface
                                    border.color: Theme.border
                                    border.width: 1
                                    radius: 5
                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        spacing: 10
                                        ListView {
                                            id: textureList
                                            Layout.preferredWidth: 290
                                            Layout.fillHeight: true
                                            model: textureBindingsModel
                                            clip: true
                                            spacing: 3
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                            onCountChanged: texturePanel.selectedTextureIndex = -1
                                            delegate: Rectangle {
                                                required property int index
                                                required property string textureId
                                                required property string textureDetail
                                                required property bool textureAvailable
                                                width: textureList.width - 7
                                                height: 56
                                                radius: 4
                                                color: texturePanel.selectedTextureIndex === index ? Theme.surfaceRaised : textureMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                                border.width: texturePanel.selectedTextureIndex === index ? 1 : 0
                                                border.color: Theme.accent
                                                Text { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 8; text: textureId; color: textureAvailable ? Theme.text : Theme.textMuted; font.pixelSize: 12; font.weight: Font.DemiBold }
                                                Text { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; text: textureAvailable ? textureDetail : "Find in other archives when selected"; color: Theme.textMuted; font.pixelSize: 10; elide: Text.ElideMiddle }
                                                MouseArea { id: textureMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { texturePanel.selectedTextureIndex = index; controller.selectTexture(index) } }
                                            }
                                            Text { anchors.centerIn: parent; width: parent.width - 28; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap; visible: textureList.count === 0; text: controller.hasDocument ? "No texture is linked to this material" : "Open a particle from an archive to load textures"; color: Theme.textMuted; font.pixelSize: 12 }
                                        }
                                        Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: Theme.border }
                                        Item {
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            Flickable {
                                                id: texturePreviewViewport
                                                anchors.fill: parent
                                                anchors.margins: 12
                                                visible: !texturePanel.compareTexture
                                                clip: true
                                                interactive: texturePreviewImage.status === Image.Ready
                                                flickableDirection: Flickable.HorizontalAndVerticalFlick
                                                boundsBehavior: Flickable.StopAtBounds
                                                property real zoom: 1.0
                                                property real baseScale: texturePreviewImage.sourceSize.width > 0 && texturePreviewImage.sourceSize.height > 0
                                                                          ? Math.min(width / texturePreviewImage.sourceSize.width, height / texturePreviewImage.sourceSize.height)
                                                                          : 1.0
                                                property real imageWidth: texturePreviewImage.sourceSize.width * baseScale * zoom
                                                property real imageHeight: texturePreviewImage.sourceSize.height * baseScale * zoom
                                                contentWidth: Math.max(width, imageWidth)
                                                contentHeight: Math.max(height, imageHeight)

                                                function zoomAt(pointX, pointY, factor) {
                                                    if (texturePreviewImage.status !== Image.Ready)
                                                        return
                                                    const oldImageX = texturePreviewImage.x
                                                    const oldImageY = texturePreviewImage.y
                                                    const imagePointX = (contentX + pointX - oldImageX) / imageWidth
                                                    const imagePointY = (contentY + pointY - oldImageY) / imageHeight
                                                    zoom = Math.max(1, Math.min(8, zoom * factor))
                                                    contentX = texturePreviewImage.x + imagePointX * imageWidth - pointX
                                                    contentY = texturePreviewImage.y + imagePointY * imageHeight - pointY
                                                }

                                                Image {
                                                    id: texturePreviewImage
                                                    width: texturePreviewViewport.imageWidth
                                                    height: texturePreviewViewport.imageHeight
                                                    x: (texturePreviewViewport.contentWidth - width) / 2
                                                    y: (texturePreviewViewport.contentHeight - height) / 2
                                                    source: controller.texturePreviewUrl
                                                    asynchronous: true
                                                    cache: false
                                                    visible: source !== "" && status === Image.Ready
                                                    onSourceChanged: {
                                                        texturePreviewViewport.zoom = 1
                                                        texturePreviewViewport.contentX = 0
                                                        texturePreviewViewport.contentY = 0
                                                    }
                                                }

                                                WheelHandler {
                                                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                                                    onWheel: function(event) {
                                                        texturePreviewViewport.zoomAt(
                                                            event.x, event.y,
                                                            event.angleDelta.y > 0 ? 1.15 : 1 / 1.15
                                                        )
                                                        event.accepted = true
                                                    }
                                                }
                                            }
                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.margins: 14
                                                visible: texturePanel.compareTexture
                                                spacing: 12
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    spacing: 6
                                                    Text { text: "ORIGINAL"; color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold }
                                                    Rectangle {
                                                        id: originalTextureOption
                                                        Layout.fillWidth: true
                                                        Layout.fillHeight: true
                                                        color: Theme.background
                                                        border.width: controller.selectedTextureUsesImported ? 1 : 2
                                                        border.color: controller.selectedTextureUsesImported ? Theme.border : Theme.accent
                                                        Image {
                                                            anchors.fill: parent
                                                            anchors.margins: 8
                                                            source: controller.textureOriginalPreviewUrl
                                                            fillMode: Image.PreserveAspectFit
                                                            asynchronous: true
                                                            cache: false
                                                        }
                                                        Rectangle {
                                                            anchors.top: parent.top
                                                            anchors.right: parent.right
                                                            anchors.margins: 7
                                                            visible: !controller.selectedTextureUsesImported
                                                            width: 160
                                                            height: 24
                                                            radius: 3
                                                            color: Theme.accent
                                                            Text {
                                                                anchors.centerIn: parent
                                                                text: "SELECTED FOR WRITE PATCH"
                                                                color: Theme.accentText
                                                                font.pixelSize: 9
                                                                font.weight: Font.DemiBold
                                                            }
                                                        }
                                                        MouseArea {
                                                            anchors.fill: parent
                                                            cursorShape: Qt.PointingHandCursor
                                                            onClicked: controller.setSelectedTexturePatchVersion(false)
                                                        }
                                                    }
                                                }
                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    spacing: 6
                                                    Text { text: "IMPORTED"; color: Theme.accent; font.pixelSize: 10; font.weight: Font.DemiBold }
                                                    Rectangle {
                                                        id: importedTextureOption
                                                        Layout.fillWidth: true
                                                        Layout.fillHeight: true
                                                        color: Theme.background
                                                        border.width: controller.selectedTextureUsesImported ? 2 : 1
                                                        border.color: controller.selectedTextureUsesImported ? Theme.accent : Theme.accentStrong
                                                        Image {
                                                            anchors.fill: parent
                                                            anchors.margins: 8
                                                            source: controller.texturePreviewUrl
                                                            fillMode: Image.PreserveAspectFit
                                                            asynchronous: true
                                                            cache: false
                                                        }
                                                        Rectangle {
                                                            anchors.top: parent.top
                                                            anchors.right: parent.right
                                                            anchors.margins: 7
                                                            visible: controller.selectedTextureUsesImported
                                                            width: 160
                                                            height: 24
                                                            radius: 3
                                                            color: Theme.accent
                                                            Text {
                                                                anchors.centerIn: parent
                                                                text: "SELECTED FOR WRITE PATCH"
                                                                color: Theme.accentText
                                                                font.pixelSize: 9
                                                                font.weight: Font.DemiBold
                                                            }
                                                        }
                                                        MouseArea {
                                                            anchors.fill: parent
                                                            cursorShape: Qt.PointingHandCursor
                                                            onClicked: controller.setSelectedTexturePatchVersion(true)
                                                        }
                                                    }
                                                }
                                            }
                                            Text {
                                                anchors.centerIn: parent
                                                width: parent.width - 48
                                                horizontalAlignment: Text.AlignHCenter
                                                wrapMode: Text.WordWrap
                                                text: controller.texturePreviewMessage
                                                color: Theme.textMuted
                                                font.pixelSize: 12
                                                visible: !texturePanel.compareTexture && controller.texturePreviewUrl === ""
                                            }
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                anchors.bottom: parent.bottom
                                                anchors.bottomMargin: 8
                                                text: controller.texturePreviewMessage
                                                color: Theme.textMuted
                                                font.pixelSize: 11
                                                visible: !texturePanel.compareTexture && controller.texturePreviewUrl !== ""
                                            }
                                        }
                                    }
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    visible: texturePanel.listView
                                    color: Theme.surface
                                    border.color: Theme.border
                                    border.width: 1
                                    radius: 5
                                    ListView {
                                        id: textureOverviewList
                                        anchors.fill: parent
                                        anchors.margins: 10
                                        model: textureOverviewModel
                                        clip: true
                                        spacing: 7
                                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                        delegate: Rectangle {
                                            required property int systemIndex
                                            required property var systemTextures
                                            width: textureOverviewList.width - 8
                                            height: 126
                                            color: Theme.background
                                            radius: 4
                                            border.color: Theme.border
                                            border.width: 1
                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.margins: 9
                                                spacing: 10
                                                Text {
                                                    Layout.preferredWidth: 188
                                                    Layout.fillHeight: true
                                                    text: "Particle System " + (systemIndex + 1) + ":"
                                                    color: Theme.text
                                                    font.pixelSize: 12
                                                    font.weight: Font.DemiBold
                                                    verticalAlignment: Text.AlignVCenter
                                                    elide: Text.ElideMiddle
                                                }
                                                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: Theme.border }
                                                Flickable {
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    contentWidth: overviewTextures.width
                                                    contentHeight: height
                                                    clip: true
                                                    boundsBehavior: Flickable.StopAtBounds
                                                    Row {
                                                        id: overviewTextures
                                                        spacing: 7
                                                        Repeater {
                                                            model: systemTextures
                                                            delegate: Rectangle {
                                                                required property var modelData
                                                                width: 108
                                                                height: 106
                                                                radius: 4
                                                                color: overviewMouse.containsMouse ? Theme.surfaceHover : Theme.surface
                                                                property bool isSelected: controller.selectedTextureSystemIndex === modelData.systemIndex
                                                                                          && controller.selectedTextureMaterialId === modelData.materialId
                                                                                          && controller.selectedTextureId === modelData.textureId
                                                                border.color: isSelected ? Theme.accentStrong : (modelData.available ? Theme.borderStrong : Theme.border)
                                                                border.width: isSelected ? 2 : 1
                                                                Image {
                                                                    anchors.left: parent.left
                                                                    anchors.right: parent.right
                                                                    anchors.top: parent.top
                                                                    anchors.bottom: overviewTextureId.top
                                                                    anchors.margins: 5
                                                                    source: modelData.previewUrl
                                                                    fillMode: Image.PreserveAspectFit
                                                                    asynchronous: true
                                                                    cache: false
                                                                    sourceSize.width: 192
                                                                    sourceSize.height: 192
                                                                    visible: modelData.previewState === "ready" && status === Image.Ready
                                                                }
                                                                Text {
                                                                    anchors.centerIn: parent
                                                                    width: parent.width - 12
                                                                    visible: modelData.previewState !== "ready"
                                                                    text: modelData.previewState === "loading" ? "Loading..." : "Can't load"
                                                                    color: modelData.available ? Theme.text : Theme.textMuted
                                                                    font.pixelSize: 10
                                                                    horizontalAlignment: Text.AlignHCenter
                                                                    wrapMode: Text.WordWrap
                                                                }
                                                                Text {
                                                                    id: overviewTextureId
                                                                    anchors.left: parent.left
                                                                    anchors.right: parent.right
                                                                    anchors.bottom: parent.bottom
                                                                    anchors.margins: 5
                                                                    text: modelData.textureId
                                                                    color: Theme.textMuted
                                                                    font.pixelSize: 9
                                                                    elide: Text.ElideMiddle
                                                                    visible: modelData.previewUrl !== ""
                                                                }
                                                                MouseArea {
                                                                    id: overviewMouse
                                                                    anchors.fill: parent
                                                                    hoverEnabled: true
                                                                    cursorShape: Qt.PointingHandCursor
                                                                    onClicked: controller.selectTextureBinding(modelData.systemIndex, modelData.materialId, modelData.textureId)
                                                                }
                                                                ToolTip.visible: overviewMouse.containsMouse && modelData.previewState === "failed"
                                                                ToolTip.text: modelData.detail
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        Text {
                                            anchors.centerIn: parent
                                            visible: textureOverviewList.count === 0
                                            text: controller.hasDocument ? "No textures are linked to this particle" : "Open a particle from an archive to load textures"
                                            color: Theme.textMuted
                                            font.pixelSize: 12
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            id: assetPanel
                            property int selectedAssetIndex: -1
                            property bool selectedTexture: false
                            Component.onCompleted: controller.searchFoundArchives("")
                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 16
                                spacing: 12
                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: controller.hasArchive ? "LOAD ARCHIVE  " + controller.archiveName : "LOAD ARCHIVE"
                                        color: Theme.text
                                        font.pixelSize: 15
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideMiddle
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: controller.stagedChangeCount > 0 ? controller.stagedChangeCount + " STAGED" : ""
                                        color: Theme.accent
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    PmButton { text: "Select"; tooltip: "Select a game or mod archive file"; onClicked: controller.selectArchiveFile() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    PmTextField {
                                        id: archiveInput
                                        Layout.fillWidth: true
                                        placeholderText: "Archive ID or found archive name"
                                        inputMethodHints: Qt.ImhNoPredictiveText
                                        onTextChanged: controller.searchFoundArchives(text)
                                        onAccepted: controller.loadArchive(text)
                                    }
                                    PmButton { text: "Load"; enabled: archiveInput.text.length > 0; onClicked: controller.loadArchive(archiveInput.text) }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 12
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        color: Theme.surface
                                        border.width: 1
                                        border.color: Theme.border
                                        radius: 6
                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            spacing: 8
                                            Text { text: "FOUND ARCHIVES"; color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold }
                                            ListView {
                                                id: foundArchiveList
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                model: foundArchivesModel
                                                clip: true
                                                spacing: 3
                                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                                delegate: Rectangle {
                                                    required property int index
                                                    required property string archiveId
                                                    required property string archiveDisplayName
                                                    width: foundArchiveList.width - 8
                                                    height: 52
                                                    radius: 4
                                                    color: foundArchiveMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                                    Text { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8; text: archiveDisplayName; color: Theme.text; font.pixelSize: 11; elide: Text.ElideRight }
                                                    Text { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; text: archiveId; color: Theme.textMuted; font.pixelSize: 10 }
                                                    MouseArea { id: foundArchiveMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: controller.loadFoundArchive(index) }
                                                }
                                                Text { anchors.centerIn: parent; visible: foundArchiveList.count === 0; text: "Search by name to show found archives"; color: Theme.textMuted; font.pixelSize: 12 }
                                            }
                                        }
                                    }
                                    Rectangle {
                                        visible: false
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        color: Theme.surface
                                        border.width: 1
                                        border.color: Theme.border
                                        radius: 6
                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            spacing: 8
                                            RowLayout {
                                                Layout.fillWidth: true
                                                Text { text: "PARTICLE ASSETS  " + controller.assetCount; color: Theme.textMuted; font.pixelSize: 10; font.weight: Font.DemiBold; Layout.fillWidth: true }
                                                PmButton { text: "Import PNG"; enabled: assetPanel.selectedTexture; onClicked: controller.importSelectedTexturePng() }
                                                PmButton { text: "Import DDS"; enabled: assetPanel.selectedTexture; onClicked: controller.importSelectedTextureDds() }
                                            }
                                            ListView {
                                                id: assetList
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                model: assetLinksModel
                                                clip: true
                                                spacing: 3
                                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                                onCountChanged: { assetPanel.selectedAssetIndex = -1; assetPanel.selectedTexture = false }
                                                delegate: Rectangle {
                                                    required property int index
                                                    required property string assetKind
                                                    required property string assetId
                                                    required property string assetDetail
                                                    required property bool assetAvailable
                                                    required property bool assetReplaceable
                                                    width: assetList.width - 8
                                                    height: 58
                                                    radius: 4
                                                    color: assetPanel.selectedAssetIndex === index ? Theme.surfaceRaised : assetMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                                    border.width: assetPanel.selectedAssetIndex === index ? 1 : 0
                                                    border.color: Theme.accent
                                                    Text { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 8; text: assetKind.toUpperCase() + "  " + assetId; color: assetAvailable ? Theme.text : Theme.textMuted; font.pixelSize: 12; font.weight: Font.DemiBold }
                                                    Text { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 8; text: assetAvailable ? assetDetail : "Not present in the loaded archive"; color: Theme.textMuted; font.pixelSize: 10; elide: Text.ElideMiddle }
                                                    MouseArea { id: assetMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { assetPanel.selectedAssetIndex = index; assetPanel.selectedTexture = assetReplaceable; controller.selectAsset(index) } }
                                                }
                                                Text { anchors.centerIn: parent; visible: assetList.count === 0; text: controller.hasDocument && controller.hasArchive ? "No linked assets found" : "Open an archive particle to inspect links"; color: Theme.textMuted; font.pixelSize: 12 }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            ColumnLayout {
                                anchors.centerIn: parent
                                width: Math.min(440, parent.width - 48)
                                spacing: 10
                                Text {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: "PM ParticleModder"
                                    color: Theme.text
                                    font.pixelSize: 22
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    Layout.fillWidth: true
                                    horizontalAlignment: Text.AlignHCenter
                                    text: "Open a archive, .particle file or a project to start"
                                    color: Theme.textMuted
                                    font.pixelSize: 13
                                    wrapMode: Text.WordWrap
                                }
                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter
                                    spacing: 8
                                    PmButton {
                                        text: "Open Archive"
                                        onClicked: window.sectionIndex = 6
                                    }
                                    PmButton {
                                        text: "Open .particle"
                                        onClicked: controller.openFiles()
                                    }
                                    PmButton {
                                        text: "Open Project"
                                        onClicked: controller.openProject()
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: !controller.hasGameDataDirectory
                                    horizontalAlignment: Text.AlignHCenter
                                    text: "HELLDIVERS 2 DATA FOLDER NOT SELECTED"
                                    color: Theme.danger
                                    font.pixelSize: 11
                                    font.weight: Font.DemiBold
                                }
                                PmButton {
                                    Layout.alignment: Qt.AlignHCenter
                                    visible: !controller.hasGameDataDirectory
                                    text: "Add Game Folder Path"
                                    warning: true
                                    onClicked: controller.selectGameDataDirectory()
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            color: Theme.surface
            border.width: 0
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                Text { Layout.fillWidth: true; text: controller.statusMessage; color: Theme.textMuted; font.pixelSize: 11; elide: Text.ElideRight }
                Text { text: controller.hasDocument ? controller.versionText : ""; color: Theme.textMuted; font.pixelSize: 11 }
            }
        }
    }

    component IdField: RowLayout {
        id: idFieldRoot
        property string label
        property string value
        property string field
        property int row
        Layout.fillWidth: true
        Layout.preferredHeight: visible ? 46 : 0
        spacing: 10
        Text { text: idFieldRoot.label; color: Theme.textMuted; font.pixelSize: 11; Layout.preferredWidth: 88 }
        PmTextField {
            Layout.fillWidth: true
            text: idFieldRoot.value
            inputMethodHints: Qt.ImhDigitsOnly
            onEditingFinished: controller.setVisualizerId(idFieldRoot.row, idFieldRoot.field, text)
        }
    }

    DropArea {
        anchors.fill: parent
        onDropped: function(drop) {
            if (drop.hasUrls) {
                controller.openUrls(drop.urls)
                drop.acceptProposedAction()
            }
        }
    }
}
