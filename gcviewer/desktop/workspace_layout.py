"""Menus, context inspector and appearance for the desktop workspace."""
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QMessageBox, QScrollArea, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget)

from gcviewer.desktop.appearance import apply_appearance
from gcviewer.desktop.sections import disclosure_header
from gcviewer.figures.workspace import is_comparison


class WorkspaceLayout:
    def __init__(self, window, preferences=None):
        self.w = window
        self.preferences = preferences if preferences is not None else QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, 'gcviewer', 'ChromatogramViewer')
        self.links = []
        self.appearance = self.preferences.value('appearance', 'system')
        if self.appearance not in ('system', 'light', 'dark'): self.appearance = 'system'
        self.make_inspector()
        self.make_menus()
        window.workspace_tabs.currentChanged.connect(self.sync)
        window.sample_list.currentItemChanged.connect(self.sync)
        window.sample_list.itemSelectionChanged.connect(self.sync)
        self.timer = QTimer(window)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.sync)
        self.timer.start()
        self.set_appearance(self.appearance, save=False)
        window.workspace_tabs.tabBar().hide()
        self.reset()

    def action(self, menu, title, callback, *, button=None, shortcut=None):
        action = QAction(title, self.w)
        action.triggered.connect(lambda checked=False: callback())
        if shortcut: action.setShortcut(shortcut)
        menu.addAction(action)
        if button is not None: self.links.append((action, button))
        return action

    def make_menus(self):
        w, p = self.w, self.w.fid_analysis
        bar = w.menuBar()
        file = bar.addMenu('&File')
        self.open_menu = file.addMenu('Open')
        self.action(self.open_menu, 'GC-MS acquisition…', w.open_ms, shortcut='Ctrl+O')
        self.action(self.open_menu, 'GC-FID acquisitions…', w.open_fid, shortcut='Ctrl+Shift+O')
        self.action(self.open_menu, 'Sample library…', w.open_library)
        file.addSeparator()
        self.export_menu = file.addMenu('Export')
        self.export_menu.addAction(w.figure_export_action)
        self.export_menu.addAction(w.data_export_action)
        self.export_menu.addAction(p.csv_action)
        self.export_menu.addAction(p.pdf_action)
        self.export_menu.addAction(p.batch_action)
        file.addSeparator()
        self.action(file, 'Quit', w.close, shortcut='Alt+F4')
        edit = bar.addMenu('&Edit')
        self.action(edit, 'Select all visible samples', self.select_all)
        self.action(edit, 'Clear sample selection', w.sample_list.clearSelection)
        self.action(edit, 'Remove selected samples', w.remove_button.click, button=w.remove_button)
        edit.addSeparator()
        self.action(edit, 'Preferences…', self.show_preferences)
        view = bar.addMenu('&View')
        self.view_actions = []
        views = QActionGroup(w)
        views.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        for index, title in enumerate(('Figure', 'FID Analysis')):
            action = QAction(title, w, checkable=True)
            action.setShortcut(f'Ctrl+{index + 1}')
            action.triggered.connect(lambda checked=False, index=index: self.choose_view(index if checked else 0))
            views.addAction(action)
            view.addAction(action)
            self.view_actions.append(action)
        view.addSeparator()
        appearance = view.addMenu('Appearance')
        self.appearance_actions = {}
        group = QActionGroup(w)
        for value in ('system', 'light', 'dark'):
            action = QAction(value.title(), w, checkable=True)
            group.addAction(action)
            appearance.addAction(action)
            action.triggered.connect(lambda checked=False, value=value: self.set_appearance(value))
            self.appearance_actions[value] = action
        view.addSeparator()
        self.browser_action = QAction('Sample browser', w, checkable=True, checked=True)
        self.inspector_action = QAction('Inspector', w, checkable=True, checked=True)
        self.results_action = QAction('Analysis results', w, checkable=True, checked=True)
        for action in (self.browser_action, self.inspector_action, self.results_action):
            view.addAction(action)
            action.toggled.connect(self.sync)
        self.action(view, 'Reset workspace arrangement', self.reset)
        analysis = bar.addMenu('&Analysis')
        analysis.addAction(self.view_actions[1])
        analysis.addSeparator()
        analysis.addAction(p.integrate_action)
        analysis.addAction(w.integrate_selected_action)
        analysis.addAction(p.batch_action)
        analysis.addAction(w.inspect_action)
        analysis.addAction(w.compare_action)
        analysis.addSeparator()
        for kind in ('method', 'layout'):
            submenu = analysis.addMenu('FID ' + ('method and names' if kind == 'method' else 'report layout'))
            for save, title in ((False, 'Load…'), (True, 'Save…')):
                self.action(submenu, title, lambda kind=kind, save=save: p.preset(kind, save), button=p.layout_action)
        analysis.addAction(p.layout_action)
        figure = bar.addMenu('Fi&gure')
        for page in ('Style', 'Axes', 'Labels', 'Traces'):
            self.action(figure, page + ' controls', lambda page=page: self.show_figure_page(page), button=w.figure_export_action)
        self.action(figure, 'Automatic peak labels…', w.auto_labels_button.click, button=w.auto_labels_button)
        self.action(figure, 'Apply figure settings', w.apply_settings, button=w.figure_export_action)
        self.action(figure, 'Reset report and labels', w.reset_report, button=w.figure_export_action)
        help_menu = bar.addMenu('&Help')
        self.action(help_menu, 'Workspace guide', lambda: QMessageBox.information(w, 'Workspace guide',
            'Choose View → Figure (Ctrl+1) or FID Analysis (Ctrl+2). The inspector follows the view. '
            'Analysis → Compare samples creates a comparison in the Figure view. '
            'Use Style / Axes / Labels for figure editing, Method / Names / Advanced for FID analysis. '
            'Apply figure settings after editing. View hides/shows panels; Reset restores them.\n\n'
            'Drag samples to reorder; drag empty list space to select. Shift/Ctrl extend selection. '
            'Remove affects this session, never the original files.\n\n'
            'Edit → Preferences selects appearance. Figure exports keep white paper.'))
        self.action(help_menu, 'Publication guidelines…', w.show_figure_guidelines, button=w.figure_export_action)
        self.action(help_menu, 'About', lambda: QMessageBox.information(w, 'Chromatogram Viewer',
            'Chromatogram Viewer\nGC-MS inspection, GC-FID analysis and publication figures.\n'
            'Retention-time assignments are not confirmed identities.'))

    def make_inspector(self):
        w, p = self.w, self.w.fid_analysis
        self.inspector = QStackedWidget()
        self.inspector.setMinimumWidth(280)
        w.splitter.addWidget(self.inspector)
        self.figure_page = QWidget()
        outer = QVBoxLayout(self.figure_page)
        outer.setContentsMargins(4, 0, 0, 0)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.pages, self.forms = {}, {}
        for name in ('Style', 'Axes', 'Labels', 'Traces'):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(6, 6, 6, 6)
            if name in ('Style', 'Axes'):
                form = QFormLayout()
                form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
                layout.addLayout(form)
                self.forms[name] = form
            layout.addStretch()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, name)
            self.pages[name] = layout
        advanced_section = QWidget()
        advanced_layout = QVBoxLayout(advanced_section)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.advanced_body = QWidget()
        self.forms['Advanced'] = QFormLayout(self.advanced_body)
        self.forms['Advanced'].setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.advanced = disclosure_header('Typography and output', self.advanced_body)
        advanced_layout.addWidget(self.advanced)
        advanced_layout.addWidget(self.advanced_body)
        self.pages['Style'].insertWidget(1, advanced_section)
        self.forms['Actions'] = QFormLayout()
        outer.addLayout(self.forms['Actions'])
        self.inspector.addWidget(self.figure_page)
        self.analysis_page = QWidget()
        layout = QVBoxLayout(self.analysis_page)
        layout.setContentsMargins(4, 0, 0, 0)
        self.inspector.addWidget(self.analysis_page)
        layout.addWidget(p.forms)
        p.forms.show()
        w.make_settings(self.forms, self.pages)

    def set_appearance(self, mode, *, save=True):
        if mode not in ('system', 'light', 'dark'): mode = 'system'
        self.appearance = mode
        apply_appearance(mode)
        self.appearance_actions[mode].setChecked(True)
        if save:
            self.preferences.setValue('appearance', mode)
            self.preferences.sync()
        QTimer.singleShot(0, self.w.redraw)

    def sync(self, *args):
        if not hasattr(self, 'view_actions') or self.w.sample_list.selection_interaction:
            return
        w, p = self.w, self.w.fid_analysis
        analysis = w.workspace_tabs.currentIndex() == 1
        comparison = bool(w.active and is_comparison(w.active.trace))
        for action, button in self.links: action.setEnabled(button.isEnabled())
        available = w.workspace_tabs.isTabEnabled(1)
        self.view_actions[1].setEnabled(available)
        self.view_actions[1].setStatusTip('Analyse the active FID acquisition' if available else 'Open and select a GC-FID acquisition to use this view')
        self.view_actions[int(analysis)].setChecked(True)
        w.sample_panel.setVisible(self.browser_action.isChecked())
        show = self.inspector_action.isChecked()
        self.inspector.setVisible(show)
        self.inspector.setCurrentIndex(1 if analysis else 0)
        self.figure_page.setEnabled(w.active is not None)
        self.tabs.setTabVisible(3, comparison)
        w.comparison_controls.setVisible(comparison)
        p.result_pane.setVisible(self.results_action.isChecked())
        self.results_action.setEnabled(analysis)

    def choose_view(self, index):
        if self.w.workspace_tabs.isTabEnabled(index):
            self.w.workspace_tabs.setCurrentIndex(index)
        self.sync()

    def select_all(self):
        for row in range(self.w.sample_list.count()):
            item = self.w.sample_list.item(row)
            item.setSelected(not item.isHidden())

    def show_figure_page(self, page):
        self.w.workspace_tabs.setCurrentIndex(0)
        self.inspector_action.setChecked(True)
        self.tabs.setCurrentIndex(('Style', 'Axes', 'Labels', 'Traces').index(page))

    def reset(self):
        for action in (self.browser_action, self.inspector_action, self.results_action): action.setChecked(True)
        self.w.splitter.setSizes([220, 760, 280])
        self.w.fid_analysis.results_split.setSizes([480, 180])
        self.sync()

    def show_preferences(self):
        dialog = QDialog(self.w)
        dialog.setWindowTitle('Preferences')
        root = QVBoxLayout(dialog)
        form = QFormLayout()
        theme = QComboBox()
        theme.addItems(['System', 'Light', 'Dark'])
        theme.setCurrentIndex(('system', 'light', 'dark').index(self.appearance))
        form.addRow('Appearance', theme)
        root.addLayout(form)
        root.addWidget(QLabel('Changes keep loaded samples and edits. Figure paper stays white.'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_appearance(('system', 'light', 'dark')[theme.currentIndex()])
