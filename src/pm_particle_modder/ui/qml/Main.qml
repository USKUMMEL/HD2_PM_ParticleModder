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
    Shortcut { sequence: StandardKey.Save; enabled: controller.hasDocument; onActivated: controller.saveCurrent() }
    Shortcut { sequence: StandardKey.SaveAs; enabled: controller.hasDocument; onActivated: controller.saveCurrentAs() }
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

            Column {
                Layout.preferredWidth: 190
                spacing: 1
                Text {
                    text: "PM ParticleModder"
                    color: Theme.text
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "PERSONAL MODDER"
                    color: Theme.accent
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                }
            }

            Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; Layout.topMargin: 11; Layout.bottomMargin: 11; color: Theme.border }
            PmButton { text: "Open"; accent: true; tooltip: "Open particle files"; onClicked: controller.openFiles() }
            PmButton { text: "Game Data"; tooltip: "Select the Helldivers 2 data folder"; onClicked: controller.selectGameDataDirectory() }
            PmButton { text: "Load Archive"; tooltip: "Load an archive by ID or found archive name"; onClicked: window.sectionIndex = 5 }
            PmButton { text: "Save"; enabled: controller.hasDocument; tooltip: "Save current file"; onClicked: controller.saveCurrent() }
            PmButton { text: "Save As"; enabled: controller.hasDocument; tooltip: "Save current file as"; onClicked: controller.saveCurrentAs() }
            PmButton { text: "Save All"; enabled: controller.hasDocument; tooltip: "Save all modified files"; onClicked: controller.saveAll() }
            PmButton { text: "Project"; enabled: controller.documentCount > 0; tooltip: "Save PM project"; onClicked: controller.saveProject() }
            PmButton { text: "Write Patch"; enabled: controller.stagedChangeCount > 0; tooltip: "Write staged archive changes"; onClicked: controller.writePatch() }
            Item { Layout.fillWidth: true }
            PmButton { text: "Undo"; enabled: controller.canUndo; tooltip: "Undo last edit"; onClicked: controller.undo() }
            PmButton { text: "Redo"; enabled: controller.canRedo; tooltip: "Redo last edit"; onClicked: controller.redo() }
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
                Layout.preferredWidth: window.sidePanelExpanded ? 264 : 46
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
                                    anchors.left: parent.left
                                    anchors.right: particleClose.left
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: particleDelegate.title + (particleDelegate.dirty ? " *" : "")
                                    color: window.particleIsSelected(particleDelegate.index)
                                           || controller.currentIndex === particleDelegate.index ? Theme.text : Theme.textMuted
                                    font.pixelSize: 11
                                    elide: Text.ElideMiddle
                                }
                                Rectangle {
                                    id: particleClose
                                    width: 24
                                    height: 24
                                    anchors.right: parent.right
                                    anchors.rightMargin: 3
                                    anchors.verticalCenter: parent.verticalCenter
                                    radius: 3
                                    color: particleCloseMouse.containsMouse ? Theme.surfaceHover : "transparent"
                                    Text { anchors.centerIn: parent; text: "x"; color: Theme.textMuted; font.pixelSize: 13 }
                                    MouseArea {
                                        id: particleCloseMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        controller.closeDocument(particleDelegate.index)
                                        window.clearParticleSelection()
                                    }
                                    }
                                }
                                MouseArea {
                                    id: particleMouse
                                    anchors.left: parent.left
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    anchors.right: particleClose.left
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
                        model: ["Color", "Opacity", "Intensity", "Lifetime", "Visualizers", "Archive"]
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
                    Text {
                        Layout.fillWidth: true
                        text: controller.hasDocument ? "VERSION  " + controller.versionText : "NO DOCUMENT"
                        color: Theme.textMuted
                        font.pixelSize: 10
                        horizontalAlignment: Text.AlignHCenter
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
                        text: "Close selected from PM"
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
                        currentIndex: controller.hasDocument || window.sectionIndex === 5
                                      ? window.sectionIndex : 6

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
                                    width: visualizerList.width - 12
                                    height: 74 + (hasMaterial ? 54 : 0) + (hasUnit ? 54 : 0) + (hasMesh ? 54 : 0)
                                    radius: 6
                                    color: Theme.surface
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
                                    PmButton { text: "Game Data"; accent: true; onClicked: controller.selectGameDataDirectory() }
                                    PmButton { text: "Write Patch"; enabled: controller.stagedChangeCount > 0; onClicked: controller.writePatch() }
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
                            Column {
                                anchors.centerIn: parent
                                spacing: 8
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "PM ParticleModder"
                                    color: Theme.text
                                    font.pixelSize: 22
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "Open a .particles file to begin"
                                    color: Theme.textMuted
                                    font.pixelSize: 13
                                }
                                PmButton {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "Open File"
                                    accent: true
                                    onClicked: controller.openFiles()
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
