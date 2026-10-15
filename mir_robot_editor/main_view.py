from PySide6.QtWidgets import QLabel, QToolBar
from mir_utils.ui.widgets import MainWindowBase
from mir_robot_editor.motor_configuration.motor_configuration_view import MotorConfigurationView
from mir_robot_editor.edit_configuration_view import EditConfigurationView
from mir_robot_editor.motor_configuration.motor_configuration_view_model import MotorConfigurationViewModel
from mir_robot_editor.scan_devices_view import ScanDevicesView
from mir_robot_editor.main_viewmodel import MainViewModel, MainVMAction, MainViewModelState
from mir_robot_editor.robot_monitor_view import RobotMonitorView
from mir_robot_editor.robot_model.robot_model_view import RobotModelView
from mir_robot_editor.robot_model.structure_editor_view import StructureEditorView
from mir_utils.ui.view_base import ViewBase


class MainView(MainWindowBase, ViewBase[MainViewModel, MainVMAction]):
    def __init__(self, view_model: MainViewModel):
        super().__init__(parent=None, default_width=800, default_height=600, view_model=view_model)
        self._view_model.state_changed.connect(self._on_state_changed)
        self._view_model.title_changed.connect(lambda title:self.setWindowTitle(title))
        self.setWindowTitle("MirRobotEditor")
        self._new_action = self._make_action(MainVMAction.NEW, self._view_model.new, "new", "Ctrl+N")
        self._save_action = self._make_action(MainVMAction.SAVE, self._view_model.save, "save", "Ctrl+S")
        self._save_as_action = self._make_action(MainVMAction.SAVE_AS, self._view_model.save_as, "", "Ctrl+Shift+S")
        self._open_action = self._make_action(MainVMAction.OPEN, self._view_model.load_configuration, "folder-open", "Ctrl+O")
        self._connect_action = self._make_action(MainVMAction.CONNECT, self._view_model.connect_robot, "cable")                
        self._disconnect_action = self._make_action(MainVMAction.DISCONNECT, self._view_model.disconnect_robot, "unplug")                
        self._scan_action = self._make_action(MainVMAction.SCAN, self.on_action_scan, "scan")                
        self._edit_configuration_action = self._make_action(MainVMAction.EDIT_CONFIGURATION, self.on_action_edit_configuration, "edit")
        self._motor_cfg_action = self._make_action(MainVMAction.MOTOR_CFG, self.on_action_motor_cfg, "gear")                
        self._structure_action = self._make_action(MainVMAction.STRUCTURE, self.on_action_structure, "structure")
        self._robot_model_action = self._make_action(MainVMAction.ROBOT_MODEL, self.on_action_robot_model, "robot")
        self._quit_action = self._make_action(MainVMAction.QUIT, self.on_quit, "")

        toolbar = QToolBar("Main toolbar")
        self.addToolBar(toolbar)
        for action in [ self._new_action,
                        self._save_action, 
                        self._open_action, 
                        self._connect_action, 
                        self._disconnect_action, 
                        self._scan_action, 
                        self._edit_configuration_action, 
                        self._motor_cfg_action,
                        self._structure_action,
                        self._robot_model_action]:
              toolbar.addAction(action)

        menu = self.menuBar()
        file_menu = menu.addMenu("Fichier")
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._save_as_action)
        file_menu.addAction(self._edit_configuration_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

        robot_menu = menu.addMenu("Robot")
        robot_menu.addAction(self._connect_action)
        robot_menu.addAction(self._disconnect_action)
        robot_menu.addAction(self._scan_action)
        robot_menu.addAction(self._structure_action)
        robot_menu.addAction(self._robot_model_action)
        
        self.robot_monitor_view = RobotMonitorView(self, view_model.get_robot_monitor_view_model(), self)
        self.robot_monitor_view.restore_state()

        self.setCentralWidget(self.robot_monitor_view)

        self._status_bar = self.statusBar()
        self._status_state = QLabel()
        self._status_bar.addWidget(self._status_state)
        
        self._view_model.update_state_notifications()

    def closeEvent(self, event):
        if self._quit_action.isEnabled():
            self.robot_monitor_view.save_state()
            return super().closeEvent(event)
        event.ignore()
    
    def on_quit(self):
        self._view_model.quit()
        super().close()
 
    def on_action_scan(self):
        self._view_model.execute_scan_devices(lambda vm: ScanDevicesView(self, vm).exec())

    def on_action_edit_configuration(self):
        self._view_model.execute_edit_configuration(lambda vm: EditConfigurationView(self, vm).exec())
        
    def on_action_motor_cfg(self):
        def open_dialog(vm: MotorConfigurationViewModel):
           dlg = MotorConfigurationView(self, vm)
           return dlg.exec()
        self._view_model.execute_motor_configuration(open_dialog)
        
    def on_action_structure(self):
        self._view_model.execute_structure_editor(lambda vm: StructureEditorView(self, vm).exec())

    def on_action_robot_model(self):
        self._view_model.execute_robot_model(lambda vm: RobotModelView(self, vm).exec())

    def _on_state_changed(self, state: MainViewModelState, description: str):
        self._status_state.setText(description)