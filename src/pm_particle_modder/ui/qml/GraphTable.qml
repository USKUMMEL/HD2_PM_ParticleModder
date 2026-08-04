pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQml.Models

Item {
    id: root
    property var tableModel
    property string kind
    property bool colorMode: false
    property bool showTimeColumns: true
    property bool restoringSelection: false
    property bool cellEditing: false
    property int selectedCount: 0
    property int dragAnchorRow: -1
    property int dragAnchorColumn: -1
    property int dragLastRow: -1
    property int dragLastColumn: -1
    property bool additiveDrag: false
    property bool subtractiveDrag: false
    property var dragBaseline: ({})
    property bool dragSelecting: false
    property color applyColor: "#FFFFFF"

    function tableColumnWidth(column) {
        if (!root.showTimeColumns && column % 2 === 0)
            return 0
        if (column % 2 === 0)
            return 92
        return root.colorMode ? 74 : 112
    }

    function cellAtPosition(x, y) {
        const row = Math.floor((y + tableView.contentY) / 37)
        if (row < 0 || row >= root.tableModel.rowCount())
            return [-1, -1]
        let remainingX = x + tableView.contentX
        for (let column = 0; column < root.tableModel.columnCount(); ++column) {
            const width = root.tableColumnWidth(column)
            if (width <= 0)
                continue
            if (remainingX < width)
                return [row, column]
            remainingX -= width + 1
        }
        return [-1, -1]
    }

    function selectRectangle(firstRow, lastRow, firstColumn, lastColumn, command) {
        if (firstRow > lastRow || firstColumn > lastColumn)
            return
        for (let row = firstRow; row <= lastRow; ++row) {
            for (let column = firstColumn; column <= lastColumn; ++column) {
                cellSelection.select(root.tableModel.cellIndex(row, column), command)
            }
        }
    }

    function updateRectangleDifference(
            sourceFirstRow, sourceLastRow, sourceFirstColumn, sourceLastColumn,
            otherFirstRow, otherLastRow, otherFirstColumn, otherLastColumn, command) {
        const overlapFirstRow = Math.max(sourceFirstRow, otherFirstRow)
        const overlapLastRow = Math.min(sourceLastRow, otherLastRow)
        const overlapFirstColumn = Math.max(sourceFirstColumn, otherFirstColumn)
        const overlapLastColumn = Math.min(sourceLastColumn, otherLastColumn)
        if (overlapFirstRow > overlapLastRow || overlapFirstColumn > overlapLastColumn) {
            root.selectRectangle(
                sourceFirstRow, sourceLastRow, sourceFirstColumn, sourceLastColumn, command
            )
            return
        }
        root.selectRectangle(
            sourceFirstRow, overlapFirstRow - 1,
            sourceFirstColumn, sourceLastColumn, command
        )
        root.selectRectangle(
            overlapLastRow + 1, sourceLastRow,
            sourceFirstColumn, sourceLastColumn, command
        )
        root.selectRectangle(
            overlapFirstRow, overlapLastRow,
            sourceFirstColumn, overlapFirstColumn - 1, command
        )
        root.selectRectangle(
            overlapFirstRow, overlapLastRow,
            overlapLastColumn + 1, sourceLastColumn, command
        )
    }

    function restoreBaselineDifference(
            sourceFirstRow, sourceLastRow, sourceFirstColumn, sourceLastColumn,
            otherFirstRow, otherLastRow, otherFirstColumn, otherLastColumn) {
        const overlapFirstRow = Math.max(sourceFirstRow, otherFirstRow)
        const overlapLastRow = Math.min(sourceLastRow, otherLastRow)
        const overlapFirstColumn = Math.max(sourceFirstColumn, otherFirstColumn)
        const overlapLastColumn = Math.min(sourceLastColumn, otherLastColumn)

        function restoreRectangle(firstRow, lastRow, firstColumn, lastColumn) {
            for (let row = firstRow; row <= lastRow; ++row) {
                for (let column = firstColumn; column <= lastColumn; ++column) {
                    const index = root.tableModel.cellIndex(row, column)
                    const key = row + ":" + column
                    cellSelection.select(
                        index,
                        root.dragBaseline[key]
                            ? ItemSelectionModel.Select
                            : ItemSelectionModel.Deselect
                    )
                }
            }
        }

        if (overlapFirstRow > overlapLastRow || overlapFirstColumn > overlapLastColumn) {
            restoreRectangle(sourceFirstRow, sourceLastRow, sourceFirstColumn, sourceLastColumn)
            return
        }
        restoreRectangle(sourceFirstRow, overlapFirstRow - 1, sourceFirstColumn, sourceLastColumn)
        restoreRectangle(overlapLastRow + 1, sourceLastRow, sourceFirstColumn, sourceLastColumn)
        restoreRectangle(overlapFirstRow, overlapLastRow, sourceFirstColumn, overlapFirstColumn - 1)
        restoreRectangle(overlapFirstRow, overlapLastRow, overlapLastColumn + 1, sourceLastColumn)
    }

    function selectRange(endRow, endColumn) {
        if (endRow === root.dragLastRow && endColumn === root.dragLastColumn)
            return
        const firstRow = Math.min(root.dragAnchorRow, endRow)
        const lastRow = Math.max(root.dragAnchorRow, endRow)
        const firstColumn = Math.min(root.dragAnchorColumn, endColumn)
        const lastColumn = Math.max(root.dragAnchorColumn, endColumn)
        const previousFirstRow = Math.min(root.dragAnchorRow, root.dragLastRow)
        const previousLastRow = Math.max(root.dragAnchorRow, root.dragLastRow)
        const previousFirstColumn = Math.min(root.dragAnchorColumn, root.dragLastColumn)
        const previousLastColumn = Math.max(root.dragAnchorColumn, root.dragLastColumn)

        if (!root.additiveDrag) {
            root.updateRectangleDifference(
                previousFirstRow, previousLastRow, previousFirstColumn, previousLastColumn,
                firstRow, lastRow, firstColumn, lastColumn, ItemSelectionModel.Deselect
            )
            root.updateRectangleDifference(
                firstRow, lastRow, firstColumn, lastColumn,
                previousFirstRow, previousLastRow, previousFirstColumn, previousLastColumn,
                ItemSelectionModel.Select
            )
        } else {
            root.updateRectangleDifference(
                firstRow, lastRow, firstColumn, lastColumn,
                previousFirstRow, previousLastRow, previousFirstColumn, previousLastColumn,
                root.subtractiveDrag
                    ? ItemSelectionModel.Deselect
                    : ItemSelectionModel.Select
            )
            root.restoreBaselineDifference(
                previousFirstRow, previousLastRow, previousFirstColumn, previousLastColumn,
                firstRow, lastRow, firstColumn, lastColumn
            )
        }
        root.dragLastRow = endRow
        root.dragLastColumn = endColumn
    }

    function selectedCells() {
        const result = []
        const indexes = cellSelection.selectedIndexes
        for (let index = 0; index < indexes.length; ++index)
            result.push([indexes[index].row, indexes[index].column])
        return result
    }

    function applyCells() {
        const cells = root.selectedCells()
        if (!root.colorMode)
            return cells
        return cells.filter(function(cell) { return cell[1] % 2 === 1 })
    }

    function syncSelection() {
        if (root.dragSelecting)
            return
        root.selectedCount = cellSelection.selectedIndexes.length
        if (!root.restoringSelection)
            controller.updateSelection(root.kind, root.selectedCells())
    }

    function colorFromText(value) {
        const parts = value.trim().replace(/[()\[\]]/g, "").split(",")
        if (parts.length !== 3)
            return null
        const channels = []
        for (let index = 0; index < 3; ++index) {
            const channel = Number(parts[index].trim())
            if (!Number.isFinite(channel))
                return null
            channels.push(Math.max(0, Math.min(255, channel)))
        }
        return Qt.rgba(channels[0] / 255, channels[1] / 255, channels[2] / 255, 1)
    }

    function colorToText(color) {
        return Math.round(color.r * 255) + ", "
             + Math.round(color.g * 255) + ", "
             + Math.round(color.b * 255)
    }

    function setApplyColor(color) {
        root.applyColor = color
        colorValue.text = root.colorToText(color)
    }

    function syncApplyColor() {
        const indexes = cellSelection.selectedIndexes
        for (let index = 0; index < indexes.length; ++index) {
            const cell = indexes[index]
            if (cell.column % 2 === 1 && root.syncApplyColorFromCell(cell.row, cell.column))
                return
        }
    }

    function syncApplyColorFromCell(row, column) {
        if (!root.colorMode || column % 2 !== 1)
            return false
        const text = root.tableModel.cellText(row, column)
        const color = root.colorFromText(text)
        if (color === null)
            return false
        root.setApplyColor(color)
        return true
    }

    function selectCells(cells) {
        root.restoringSelection = true
        cellSelection.clear()
        for (let index = 0; index < cells.length; ++index) {
            const row = Number(cells[index][0])
            const column = Number(cells[index][1])
            if (row >= 0 && row < root.tableModel.rowCount()
                    && column >= 0 && column < root.tableModel.columnCount()) {
                cellSelection.select(root.tableModel.cellIndex(row, column), ItemSelectionModel.Select)
            }
        }
        root.restoringSelection = false
        root.syncSelection()
    }

    function restoreSelection() {
        root.selectCells(controller.selectionFor(root.kind))
    }

    Component.onCompleted: Qt.callLater(root.restoreSelection)

    Connections {
        target: root.tableModel
        function onModelAboutToBeReset() { root.restoringSelection = true }
        function onModelReset() { Qt.callLater(root.restoreSelection) }
    }

    Connections {
        target: controller
        function onTableSelectionsChanged(kind) {
            if (kind === root.kind)
                Qt.callLater(root.restoreSelection)
        }
    }

    Shortcut {
        sequence: StandardKey.Copy
        enabled: root.visible && root.selectedCount > 0
        onActivated: controller.copyTable(root.kind, root.selectedCells())
    }
    Shortcut {
        sequence: StandardKey.Paste
        enabled: root.visible && root.selectedCount > 0
        onActivated: controller.pasteTable(root.kind, root.selectedCells())
    }

    ColumnLayout {
        objectName: "graphTableLayout"
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 36
            Layout.minimumHeight: 36
            Layout.maximumHeight: 36
            spacing: 7

            PmButton {
                text: root.showTimeColumns ? "Hide Time" : "Show Time"
                tooltip: "Toggle time columns"
                onClicked: {
                    root.showTimeColumns = !root.showTimeColumns
                    tableView.forceLayout()
                }
            }
            Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; Layout.topMargin: 4; Layout.bottomMargin: 4; color: Theme.border }
            PmTextField {
                id: fillValue
                visible: !root.colorMode
                Layout.preferredWidth: 130
                placeholderText: "Value"
                onAccepted: applyButton.clicked()
            }
            Rectangle {
                objectName: root.kind + "ApplyColorSwatch"
                visible: root.colorMode
                Layout.preferredWidth: 34
                Layout.preferredHeight: 34
                radius: 4
                color: root.applyColor
                border.width: 1
                border.color: Theme.borderStrong
                ToolTip.visible: colorPickerMouse.containsMouse
                ToolTip.text: "Pick RGB color and hue"
                MouseArea {
                    id: colorPickerMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        const rgb = controller.pickApplyColor(colorValue.text)
                        const color = root.colorFromText(rgb)
                        if (color !== null)
                            root.setApplyColor(color)
                    }
                }
            }
            PmTextField {
                id: colorValue
                objectName: root.kind + "ApplyColorText"
                visible: root.colorMode
                Layout.preferredWidth: 142
                placeholderText: "R, G, B"
                text: "255, 255, 255"
                onEditingFinished: {
                    const color = root.colorFromText(text)
                    if (color !== null)
                        root.applyColor = color
                }
                onAccepted: applyButton.clicked()
            }
            Text {
                text: "CURRENT PARTICLE"
                color: Theme.textMuted
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
            PmButton {
                id: applyButton
                text: "Apply"
                enabled: root.applyCells().length > 0
                         && (root.colorMode ? root.colorFromText(colorValue.text) !== null
                                            : fillValue.text.length > 0)
                tooltip: "Apply to selected cells in the current particle"
                onClicked: controller.fillTable(
                    root.kind, root.applyCells(), root.colorMode ? colorValue.text : fillValue.text
                )
            }
            PmButton {
                visible: root.colorMode
                text: "Apply Hue"
                enabled: root.applyCells().length > 0
                tooltip: "Apply the hue from the selected apply color"
                onClicked: {
                    const hue = controller.colorHue(colorValue.text)
                    if (hue >= 0)
                        controller.fillTableHue(root.kind, root.applyCells(), hue)
                }
            }
            Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; Layout.topMargin: 4; Layout.bottomMargin: 4; color: Theme.border }
            Text {
                text: "ALL TICKED PARTICLES"
                color: Theme.textMuted
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
            PmButton {
                id: applyAppliedButton
                text: "Apply"
                enabled: controller.applyParticleCount > 0
                         && (root.colorMode ? root.colorFromText(colorValue.text) !== null
                                            : fillValue.text.length > 0)
                tooltip: "Apply to selected cells in checked particles"
                onClicked: controller.fillAppliedTables(
                    root.kind, root.colorMode ? colorValue.text : fillValue.text
                )
            }
            PmButton {
                visible: root.colorMode
                text: "Apply Hue"
                enabled: controller.applyParticleCount > 0
                tooltip: "Apply the hue from the selected apply color to checked particles"
                onClicked: {
                    const hue = controller.colorHue(colorValue.text)
                    if (hue >= 0)
                        controller.fillAppliedTablesHue(root.kind, hue)
                }
            }
            Item { Layout.fillWidth: true }
            Text {
                text: root.selectedCount + " selected"
                color: Theme.textMuted
                font.pixelSize: 11
            }
        }

        RowLayout {
            visible: root.colorMode
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 34 : 0
            Layout.minimumHeight: visible ? 34 : 0
            Layout.maximumHeight: visible ? 34 : 0
            spacing: 7
            Text {
                text: "CURRENT PARTICLE"
                color: Theme.textMuted
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            PmButton {
                text: "Select All"
                enabled: controller.hasDocument
                tooltip: "Select every cell in the current particle"
                onClicked: controller.selectAllTableCells(root.kind)
            }
            PmButton {
                text: "Deselect All"
                enabled: root.selectedCount > 0
                tooltip: "Clear the current particle selection"
                onClicked: controller.clearTableSelection(root.kind)
            }
            PmButton {
                text: "Undo Selection"
                enabled: controller.canUndoSelection
                tooltip: "Undo the last cell selection change"
                onClicked: controller.undoSelection()
            }
            PmButton {
                text: "Redo Selection"
                enabled: controller.canRedoSelection
                tooltip: "Redo the last cell selection change"
                onClicked: controller.redoSelection()
            }
        }

        Menu {
            id: colorCellMenu
            property int targetRow: -1
            property int targetColumn: -1

            MenuItem {
                text: "Color Picker"
                onTriggered: {
                    if (colorCellMenu.targetRow < 0 || colorCellMenu.targetColumn < 0)
                        return
                    const row = colorCellMenu.targetRow
                    const column = colorCellMenu.targetColumn
                    const current = root.tableModel.cellText(
                        row, column
                    )
                    const rgb = controller.pickApplyColor(current)
                    if (rgb.length > 0)
                        controller.fillTable(root.kind, root.applyCells(), rgb)
                }
            }
            MenuItem {
                text: "Hue Picker"
                onTriggered: {
                    if (colorCellMenu.targetRow < 0 || colorCellMenu.targetColumn < 0)
                        return
                    const current = root.tableModel.cellText(colorCellMenu.targetRow, colorCellMenu.targetColumn)
                    const hue = controller.pickApplyHue(current)
                    if (hue >= 0)
                        controller.fillTableHue(root.kind, root.applyCells(), hue)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.surface
            border.width: 1
            border.color: Theme.border
            radius: 5
            clip: true

            HorizontalHeaderView {
                id: horizontalHeader
                anchors.left: verticalHeader.right
                anchors.right: parent.right
                anchors.top: parent.top
                height: 34
                syncView: tableView
                clip: true
                delegate: Rectangle {
                    required property string display
                    implicitHeight: 34
                    color: Theme.surfaceRaised
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        text: parent.display
                        color: Theme.textMuted
                        font.pixelSize: 11
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                }
            }

            VerticalHeaderView {
                id: verticalHeader
                anchors.left: parent.left
                anchors.top: horizontalHeader.bottom
                anchors.bottom: parent.bottom
                width: 44
                syncView: tableView
                clip: true
                delegate: Rectangle {
                    required property string display
                    implicitWidth: 44
                    color: Theme.surfaceRaised
                    border.width: 1
                    border.color: Theme.border
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 4
                        anchors.rightMargin: 4
                        text: parent.display
                        color: Theme.text
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                }
            }

            TableView {
                id: tableView
                objectName: root.kind + "TableView"
                anchors.left: verticalHeader.right
                anchors.right: parent.right
                anchors.top: horizontalHeader.bottom
                anchors.bottom: parent.bottom
                model: root.tableModel
                selectionModel: ItemSelectionModel {
                    id: cellSelection
                    objectName: root.kind + "SelectionModel"
                    model: root.tableModel
                }
                selectionBehavior: TableView.SelectCells
                selectionMode: TableView.ExtendedSelection
                editTriggers: TableView.DoubleTapped | TableView.EditKeyPressed | TableView.AnyKeyPressed
                pointerNavigationEnabled: true
                keyNavigationEnabled: true
                acceptedButtons: Qt.NoButton
                alternatingRows: true
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                columnSpacing: 1
                rowSpacing: 1
                columnWidthProvider: function(column) { return root.tableColumnWidth(column) }
                rowHeightProvider: function(_row) { return 36 }
                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                onActiveFocusChanged: {
                    if (activeFocus)
                        root.syncSelection()
                }

                Connections {
                    target: cellSelection
                    function onSelectionChanged(_selected, _deselected) { root.syncSelection() }
                }

                delegate: Rectangle {
                    id: cell
                    required property int row
                    required property int column
                    required property string display
                    required property string cellColor
                    required property bool timeCell
                    required property bool selected
                    required property bool current
                    required property bool editing
                    implicitWidth: column % 2 === 0 ? 92 : (root.colorMode ? 170 : 112)
                    implicitHeight: 36
                    color: selected ? "#40594A"
                         : row % 2 === 0 ? Theme.surface : Theme.background
                    border.width: current ? 2 : 0
                    border.color: Theme.focus

                    Rectangle {
                        visible: root.colorMode && !cell.timeCell
                        anchors.centerIn: parent
                        width: Math.max(0, (parent.width - 8) * 0.8)
                        height: Math.max(0, (parent.height - 8) * 0.8)
                        radius: 3
                        color: cell.cellColor.length > 0 ? cell.cellColor : "transparent"
                        border.width: 1
                        border.color: "#000000"
                    }
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        visible: !root.colorMode || cell.timeCell
                        text: cell.display
                        color: Theme.text
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }

                    TableView.editDelegate: PmTextField {
                        anchors.fill: parent
                        text: cell.display
                        property bool editApplied: false

                        function applyEdit() {
                            if (editApplied)
                                return
                            editApplied = true
                            controller.setTableCell(root.kind, cell.row, cell.column, text)
                        }

                        Component.onCompleted: {
                            root.cellEditing = true
                            selectAll()
                            forceActiveFocus()
                        }
                        Component.onDestruction: root.cellEditing = false
                        onAccepted: applyEdit()
                        onEditingFinished: applyEdit()
                        TableView.onCommit: applyEdit()
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: tableView.rows === 0
                    text: "No " + root.kind + " data in this particle file"
                    color: Theme.textMuted
                    font.pixelSize: 14
                }
            }

            MouseArea {
                anchors.left: verticalHeader.right
                anchors.right: parent.right
                anchors.top: horizontalHeader.bottom
                anchors.bottom: parent.bottom
                anchors.rightMargin: 12
                anchors.bottomMargin: 12
                z: 2
                enabled: !root.cellEditing
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                hoverEnabled: true
                preventStealing: true

                onPressed: function(mouse) {
                    const cell = root.cellAtPosition(mouse.x, mouse.y)
                    if (cell[0] < 0) {
                        if (mouse.button === Qt.LeftButton && root.colorMode && cellSelection.selectedIndexes.length > 0) {
                            cellSelection.clearSelection()
                            root.syncSelection()
                        }
                        return
                    }
                    const index = root.tableModel.cellIndex(cell[0], cell[1])
                    if (mouse.button === Qt.RightButton) {
                        if (root.colorMode && cell[1] % 2 === 1) {
                            let selected = false
                            const indexes = cellSelection.selectedIndexes
                            for (let selectedIndex = 0; selectedIndex < indexes.length; ++selectedIndex) {
                                if (indexes[selectedIndex].row === cell[0] && indexes[selectedIndex].column === cell[1]) {
                                    selected = true
                                    break
                                }
                            }
                            if (!selected) {
                                cellSelection.clearSelection()
                                cellSelection.select(index, ItemSelectionModel.Select)
                            }
                            cellSelection.setCurrentIndex(index, ItemSelectionModel.NoUpdate)
                            colorCellMenu.targetRow = cell[0]
                            colorCellMenu.targetColumn = cell[1]
                            colorCellMenu.popup()
                        }
                        return
                    }
                    root.dragAnchorRow = cell[0]
                    root.dragAnchorColumn = cell[1]
                    root.dragLastRow = cell[0]
                    root.dragLastColumn = cell[1]
                    const baseline = ({})
                    const selected = cellSelection.selectedIndexes
                    for (let selectedIndex = 0; selectedIndex < selected.length; ++selectedIndex) {
                        baseline[selected[selectedIndex].row + ":" + selected[selectedIndex].column] = true
                    }
                    root.dragBaseline = baseline
                    root.additiveDrag = (mouse.modifiers & Qt.ControlModifier) !== 0
                    root.subtractiveDrag = root.additiveDrag
                                           && root.dragBaseline[cell[0] + ":" + cell[1]] === true
                    root.dragSelecting = true
                    if (root.additiveDrag) {
                        cellSelection.select(
                            index,
                            root.subtractiveDrag
                                ? ItemSelectionModel.Deselect
                                : ItemSelectionModel.Select
                        )
                    } else {
                        cellSelection.clearSelection()
                        cellSelection.select(index, ItemSelectionModel.Select)
                    }
                    cellSelection.setCurrentIndex(index, ItemSelectionModel.NoUpdate)
                    tableView.forceActiveFocus()
                }

                onPositionChanged: function(mouse) {
                    if (!pressed || root.dragAnchorRow < 0)
                        return
                    const cell = root.cellAtPosition(mouse.x, mouse.y)
                    if (cell[0] >= 0)
                        root.selectRange(cell[0], cell[1])
                }

                onReleased: {
                    root.dragSelecting = false
                    root.dragAnchorRow = -1
                    root.dragAnchorColumn = -1
                    root.dragLastRow = -1
                    root.dragLastColumn = -1
                    root.subtractiveDrag = false
                    root.dragBaseline = ({})
                    root.syncSelection()
                }

                onDoubleClicked: function(mouse) {
                    const cell = root.cellAtPosition(mouse.x, mouse.y)
                    if (cell[0] >= 0)
                        tableView.edit(root.tableModel.cellIndex(cell[0], cell[1]))
                }

                onWheel: function(wheel) { wheel.accepted = false }
            }
        }
    }
}
