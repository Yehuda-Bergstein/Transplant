import os
import re
import logging
import webbrowser
import traceback

from lib import utils, ui_text
from lib.transplant import Job, Transplanter
from lib.version import __version__
from gazelle.tracker_data import tr
from GUI.widget_bank import wb
from GUI.main_gui import MainWindow
from GUI.settings_window import SettingsWindow

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QThread, QSize

class LogForward(QObject, logging.Handler):
    log_forward = pyqtSignal(logging.LogRecord)

    def emit(self, record):
        self.log_forward.emit(record)

logger = logging.getLogger('tr')
logger.setLevel(logging.INFO)
handler = LogForward()
logger.addHandler(handler)

class TransplantThread(QThread):
    def __init__(self):
        super().__init__()
        wb.pb_stop.clicked.connect(self.stop)
        self.started.connect(lambda: logger.info(ui_text.start))
        self.started.connect(lambda: wb.go_stop_stack.setCurrentIndex(1))
        self.finished.connect(lambda: logger.info(ui_text.thread_finish))
        self.finished.connect(lambda: wb.go_stop_stack.setCurrentIndex(0))
        self.finished.connect(lambda: wb.pb_stop.clicked.disconnect(self.stop))
        self.finished.connect(self.deleteLater)

        self.stop_run = False

    def stop(self):
        self.stop_run = True

    def run(self):
        key_dict = {
            tr.RED: wb.config.value('le_key_1'),
            tr.OPS: wb.config.value('le_key_2')
        }
        transplanter = Transplanter(key_dict, **trpl_settings())

        for job in wb.job_data.jobs.copy():
            if self.stop_run:
                break
            try:
                if job not in wb.job_data.jobs:  # It's possible to remove jobs from joblist during transplanting
                    logger.warning(f'{ui_text.removed} {job.display_name}')
                    continue
                try:
                    success = transplanter.do_your_job(job)
                except Exception:
                    logger.exception('')
                    continue
                if success:
                    wb.job_data.remove_this_job(job)

            finally:
                logger.info('')


def start_up():
    config_version = wb.config.value('config_version')
    if config_version != __version__:
        config_update()
        wb.config.setValue('config_version', __version__)

    wb.main_window = MainWindow()
    wb.settings_window = SettingsWindow(wb.main_window)
    main_connections()
    config_connections()
    load_config()
    wb.emit_state()
    wb.pb_scan.setFocus()
    wb.main_window.show()


def config_update():
    changes = (
        ('te_rel_descr', 'te_rel_descr_templ', None),
        ('te_src_descr', 'te_src_descr_templ', None),
        ('le_scandir', 'le_scan_dir', None),
        ('geometry/header', 'geometry/job_view_header', None),
        ('le_data_dir', 'fsb_data_dir', lambda x: [x]),
        ('le_scan_dir', 'fsb_scan_dir', lambda x: [x]),
        ('le_dtor_save_dir', 'fsb_dtor_save_dir', lambda x: [x]),
    )
    for old, new, conversion in changes:
        if wb.config.contains(old):
            value = wb.config.value(old)
            if conversion:
                value = conversion(value)
            wb.config.setValue(new, value)
            wb.config.remove(old)

    for key in wb.config.allKeys():
        if key.startswith('chb_'):
            value = wb.config.value(key)
            if value not in (0, 1, 2):
                value = 2 if bool(int(value)) else 0
                wb.config.setValue(key, value)
        elif key.startswith('spb_'):
            value = wb.config.value(key)
            if not type(value) == int:
                wb.config.setValue(key, int(value))
        if key == 'spb_splitter_weight':
            wb.config.remove(key)
        if key == 'bg_source' and wb.config.value(key) == 0:
            wb.config.setValue(key, 1)


def main_connections():
    handler.log_forward.connect(print_logs)
    wb.te_paste_box.plain_text_changed.connect(lambda x: wb.pb_add.setEnabled(bool(x)))
    wb.bg_source.idClicked.connect(lambda x: wb.config.setValue('bg_source', x))
    wb.pb_add.clicked.connect(parse_paste_input)
    wb.pb_open_dtors.clicked.connect(select_dtors)
    wb.pb_scan.clicked.connect(scan_dtorrents)
    wb.pb_clear_j.clicked.connect(wb.job_data.clear)
    wb.pb_clear_r.clicked.connect(wb.result_view.clear)
    wb.pb_rem_sel.clicked.connect(remove_selected)
    wb.pb_crop.clicked.connect(crop)
    wb.pb_del_sel.clicked.connect(delete_selected)
    wb.pb_rem_tr1.clicked.connect(lambda: wb.job_data.filter_for_attr('src_tr', tr.RED))
    wb.pb_rem_tr2.clicked.connect(lambda: wb.job_data.filter_for_attr('src_tr', tr.OPS))
    wb.pb_open_tsavedir.clicked.connect(
        lambda: utils.open_local_folder(wb.fsb_dtor_save_dir.currentText()))
    wb.tb_go.clicked.connect(gogogo)
    wb.pb_open_upl_urls.clicked.connect(open_tor_urls)
    wb.job_view.horizontalHeader().sectionDoubleClicked.connect(wb.job_data.header_double_clicked)
    wb.selection.selectionChanged.connect(lambda: wb.pb_rem_sel.setEnabled(wb.selection.hasSelection()))
    wb.selection.selectionChanged.connect(
        lambda: wb.pb_crop.setEnabled(0 < len(wb.selection.selectedRows()) < len(wb.job_data.jobs)))
    wb.selection.selectionChanged.connect(lambda x: wb.pb_del_sel.setEnabled(wb.selection.hasSelection()))
    wb.job_view.doubleClicked.connect(open_torrent_page)
    wb.job_view.key_override_sig.connect(key_press)
    wb.main_window.key_press.connect(key_press)
    wb.job_data.layout_changed.connect(lambda: wb.tb_go.setEnabled(bool(wb.job_data)))
    wb.job_data.layout_changed.connect(lambda: wb.pb_clear_j.setEnabled(bool(wb.job_data)))
    wb.job_data.layout_changed.connect(
        lambda: wb.pb_rem_tr1.setEnabled(any(j.src_tr == tr.RED for j in wb.job_data)))
    wb.job_data.layout_changed.connect(
        lambda: wb.pb_rem_tr2.setEnabled(any(j.src_tr == tr.OPS for j in wb.job_data)))
    wb.result_view.textChanged.connect(
        lambda: wb.pb_clear_r.setEnabled(bool(wb.result_view.toPlainText())))
    wb.result_view.textChanged.connect(
        lambda: wb.pb_open_upl_urls.setEnabled('torrentid' in wb.result_view.toPlainText()))
    wb.tb_open_config.clicked.connect(wb.settings_window.open)
    wb.tb_open_config2.clicked.connect(wb.tb_open_config.click)
    wb.splitter.splitterMoved.connect(lambda x, y: wb.tb_open_config2.setHidden(bool(x)))
    wb.tabs.currentChanged.connect(wb.view_stack.setCurrentIndex)
    wb.view_stack.currentChanged.connect(wb.tabs.setCurrentIndex)
    wb.view_stack.currentChanged.connect(wb.button_stack.setCurrentIndex)


def config_connections():
    wb.pb_def_descr.clicked.connect(default_descr)
    wb.pb_ok.clicked.connect(settings_check)
    wb.pb_cancel.clicked.connect(wb.settings_window.reject)
    wb.settings_window.accepted.connect(
        lambda: wb.config.setValue('geometry/config_window_size', wb.settings_window.size()))
    wb.settings_window.accepted.connect(consolidate_fsbs)
    wb.fsb_scan_dir.list_changed.connect(
        lambda: wb.pb_scan.setEnabled(bool(wb.fsb_scan_dir.currentText())))
    wb.fsb_dtor_save_dir.list_changed.connect(
        lambda: wb.pb_open_tsavedir.setEnabled(bool(wb.fsb_dtor_save_dir.currentText())))
    wb.chb_show_tips.stateChanged.connect(tooltips)
    wb.spb_verbosity.valueChanged.connect(set_verbosity)
    wb.chb_show_add_dtors.stateChanged.connect(lambda x: wb.pb_open_dtors.setVisible(x)),
    wb.chb_show_rem_tr1.stateChanged.connect(lambda x: wb.pb_rem_tr1.setVisible(x)),
    wb.chb_show_rem_tr2.stateChanged.connect(lambda x: wb.pb_rem_tr2.setVisible(x)),
    wb.chb_no_icon.stateChanged.connect(wb.job_data.layoutChanged.emit)
    wb.chb_alt_row_colour.stateChanged.connect(wb.job_view.setAlternatingRowColors)
    wb.chb_show_grid.stateChanged.connect(wb.job_view.setShowGrid)
    wb.chb_show_grid.stateChanged.connect(wb.job_data.layoutChanged.emit)
    wb.spb_row_height.valueChanged.connect(wb.job_view.verticalHeader().setDefaultSectionSize)


def load_config():
    source_id = int(wb.config.value('bg_source', defaultValue=1))
    wb.bg_source.button(source_id).click()
    wb.main_window.resize(wb.config.value('geometry/size', defaultValue=QSize(550, 500)))

    try:
        wb.main_window.move(wb.config.value('geometry/position'))
    except TypeError:
        pass

    splittersizes = [int(x) for x in wb.config.value('geometry/splitter_pos', defaultValue=[150, 345])]
    wb.splitter.setSizes(splittersizes)
    wb.splitter.splitterMoved.emit(splittersizes[0], 1)
    try:
        wb.job_view.horizontalHeader().restoreState(wb.config.value('geometry/job_view_header'))
    except TypeError:
        wb.job_view.horizontalHeader().set_all_sections_visible()

    wb.settings_window.resize(wb.config.value('geometry/config_window_size', defaultValue=QSize(400, 450)))


def key_press(event: QKeyEvent):
    if not event.modifiers():
        if event.key() == Qt.Key.Key_Backspace:
            remove_selected()
    elif event.modifiers() == Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier:
        if event.key() == Qt.Key.Key_Return:
            wb.tb_go.click()
    elif event.modifiers() == Qt.KeyboardModifier.ControlModifier:
        if event.key() == Qt.Key.Key_S:
            wb.pb_scan.click()
        if event.key() == Qt.Key.Key_Tab:
            wb.tabs.next()
        if event.key() == Qt.Key.Key_R:
            crop()
        if event.key() == Qt.Key.Key_W:
            for clr_button in (wb.pb_clear_j, wb.pb_clear_r):
                if clr_button.isVisible():
                    clr_button.click()
        if event.key() == Qt.Key.Key_O:
            if wb.pb_open_upl_urls.isVisible():
                wb.pb_open_upl_urls.click()
        # number keys:
        if 0x31 <= event.key() <= 0x39:
            nr = event.key() - 0x30
            try:
                pb_rem_tr = getattr(wb, f'pb_rem_tr{nr}')
            except AttributeError:
                return
            if pb_rem_tr.isVisible():
                pb_rem_tr.click()


LINK_REGEX = re.compile(r'(https?://)([^\s\n\r]+)')
def print_logs(record: logging.LogRecord):
    if wb.tabs.count() == 1:
        wb.tabs.addTab(ui_text.tab_results)
        wb.tabs.setCurrentIndex(1)

    if not (record.exc_info and not record.msg):
        msg = LINK_REGEX.sub(r'<a href="\1\2">\2</a>', record.msg)
        wb.result_view.add(msg)

    if record.exc_info:
        cls, ex, tb = record.exc_info
        tb_str = ''.join(traceback.format_tb(tb)).strip('\n')
        wb.result_view.add(tb_str)
        wb.result_view.add(f'{cls.__name__}: {ex}')


def trpl_settings():
    user_settings = (
        'chb_deep_search',
        'chb_save_dtors',
        'chb_del_dtors',
        'chb_file_check',
        'chb_post_compare',
        'te_rel_descr_templ',
        'te_rel_descr_own_templ',
        'chb_add_src_descr',
        'te_src_descr_templ'
    )
    settings_dict = {
        'data_dir': wb.fsb_data_dir.currentText(),
        'dtor_save_dir': wb.fsb_dtor_save_dir.currentText()
    }
    for s in user_settings:
        _, arg_name = s.split('_', maxsplit=1)
        settings_dict[arg_name] = wb.config.value(s)

    if wb.config.value('chb_rehost'):
        white_str_nospace = ''.join(wb.config.value('le_whitelist').split())
        if white_str_nospace:
            whitelist = white_str_nospace.split(',')
            settings_dict.update(img_rehost=True, whitelist=whitelist,
                                 ptpimg_key=wb.config.value('le_ptpimg_key'))

    return settings_dict


def gogogo():
    if not wb.job_data:
        return

    min_req_config = ("le_key_1", "le_key_2", "fsb_data_dir")
    if not all(wb.config.value(x) for x in min_req_config):
        wb.settings_window.open()
        return

    if wb.tabs.count() == 1:
        wb.tabs.addTab(ui_text.tab_results)
    wb.tabs.setCurrentIndex(1)

    TransplantThread().start()


def parse_paste_input():
    paste_blob = wb.te_paste_box.toPlainText()
    if not paste_blob:
        return

    wb.tabs.setCurrentIndex(0)
    src_tr = tr(wb.config.value('bg_source'))

    new_jobs = []
    for line in paste_blob.split():
        match_id = re.fullmatch(r"\d+", line)
        if match_id:
            new_jobs.append(Job(src_tr=src_tr, tor_id=line))
            continue
        match_url = re.search(r"https?://(.+?)/.+torrentid=(\d+)", line)
        if match_url:
            try:
                new_jobs.append(Job(src_dom=match_url.group(1), tor_id=match_url.group(2)))
            except AssertionError:
                continue

    if not wb.job_data.append_jobs(new_jobs):
        wb.pop_up.pop_up(f'{ui_text.pop3}')

    wb.te_paste_box.clear()


def add_jobs_from_torpaths(torpaths, **kwargs):
    new_jobs = []
    for path in torpaths:
        try:
            new_jobs.append(Job(dtor_path=path, **kwargs))
        except (AssertionError, TypeError, AttributeError):
            continue

    if wb.job_data.append_jobs(new_jobs):
        wb.job_view.setFocus()
        return True


def select_dtors():
    file_paths = QFileDialog.getOpenFileNames(wb.main_window, ui_text.sel_dtors_window_title,
                                              wb.config.value('torselect_dir'),
                                              "torrents (*.torrent);;All Files (*)")[0]
    if not file_paths:
        return

    wb.tabs.setCurrentIndex(0)
    if len(file_paths) > 1:
        common_path = os.path.commonpath(file_paths)
    else:
        common_path = os.path.dirname(file_paths[0])

    wb.config.setValue('torselect_dir', os.path.normpath(common_path))

    add_jobs_from_torpaths(file_paths)


def scan_dtorrents():
    path = wb.fsb_scan_dir.currentText()
    wb.tabs.setCurrentIndex(0)

    torpaths = [scan.path for scan in os.scandir(path) if scan.is_file() and scan.name.endswith(".torrent")]
    if torpaths:
        if add_jobs_from_torpaths(torpaths, scanned=True) is None:
            wb.pop_up.pop_up(f'{ui_text.pop2}\n{path}')
    else:
        wb.pop_up.pop_up(f'{ui_text.pop1}\n{path}')


def settings_check():
    data_dir = wb.fsb_data_dir.currentText()
    scan_dir = wb.fsb_scan_dir.currentText()
    dtor_save_dir = wb.fsb_dtor_save_dir.currentText()
    save_dtors = wb.config.value('chb_save_dtors')
    rehost = wb.config.value('chb_rehost')
    ptpimg_key = wb.config.value('le_ptpimg_key')
    add_src_descr = wb.config.value('chb_add_src_descr')

    sum_ting_wong = []
    if not os.path.isdir(data_dir):
        sum_ting_wong.append(ui_text.sum_ting_wong_1)
    if scan_dir and not os.path.isdir(scan_dir):
        sum_ting_wong.append(ui_text.sum_ting_wong_2)
    if save_dtors and not os.path.isdir(dtor_save_dir):
        sum_ting_wong.append(ui_text.sum_ting_wong_3)
    if rehost and not ptpimg_key:
        sum_ting_wong.append(ui_text.sum_ting_wong_4)
    if add_src_descr and '%src_descr%' not in wb.te_src_descr_templ.toPlainText():
        sum_ting_wong.append(ui_text.sum_ting_wong_5)
    for set_name in ('le_key_1', 'le_key_2', 'le_ptpimg_key'):
        value = wb.config.value(set_name)
        stripped = value.strip()
        if value != stripped:
            show_name = set_name.split('_', maxsplit=1)[1]
            sum_ting_wong.append(ui_text.sum_ting_wong_6.format(show_name))

    if sum_ting_wong:
        warning = QMessageBox()
        warning.setIcon(QMessageBox.Icon.Warning)
        warning.setText("- " + "\n- ".join(sum_ting_wong))
        warning.exec()
        return
    else:
        wb.settings_window.accept()


def tooltips(flag):
    for t_name, ttip in vars(ui_text).items():
        if t_name.startswith('tt_'):
            obj_name = t_name.split('_', maxsplit=1)[1]
            obj = getattr(wb, obj_name)
            obj.setToolTip(ttip if flag else '')

    wb.splitter.handle(1).setToolTip(ui_text.ttm_splitter if flag else '')


def consolidate_fsbs():
    for fsb in wb.fsbs():
        fsb.consolidate()


def default_descr():
    wb.te_rel_descr_templ.setText(ui_text.def_rel_descr)
    wb.te_rel_descr_own_templ.setText(ui_text.def_rel_descr_own)
    wb.te_src_descr_templ.setText(ui_text.def_src_descr)


def open_tor_urls():
    for piece in wb.result_view.toPlainText().split():
        if 'torrentid' in piece:
            webbrowser.open(piece)


def remove_selected():
    row_list = wb.selection.selectedRows()
    if not row_list:
        return

    wb.job_data.del_multi(row_list)


def crop():
    row_list = wb.selection.selectedRows()
    if not row_list:
        return

    reversed_selection = [x for x in range(len(wb.job_data.jobs)) if x not in row_list]
    wb.job_data.del_multi(reversed_selection)
    wb.selection.clearSelection()


def delete_selected():
    row_list = wb.selection.selectedRows()
    if not row_list:
        return

    non_scanned = 0
    for i in row_list.copy():
        job = wb.job_data.jobs[i]
        if job.scanned:
            os.remove(job.dtor_path)
        else:
            row_list.remove(i)
            non_scanned += 1

    if non_scanned:
        wb.pop_up.pop_up(ui_text.pop4.format(non_scanned, 's' if non_scanned > 1 else ''))

    wb.job_data.del_multi(row_list)


def open_torrent_page(index):
    if index.column() > 1:
        return
    job = wb.job_data.jobs[index.row()]
    domain = job.src_tr.site
    if job.info_hash:
        url = domain + 'torrents.php?searchstr=' + job.info_hash
    elif job.tor_id:
        url = domain + 'torrents.php?torrentid=' + job.tor_id
    else:
        return
    webbrowser.open(url)


def set_verbosity(lvl):
    verb_map = {
        0: logging.CRITICAL,
        1: logging.ERROR,
        2: logging.INFO,
        3: logging.DEBUG}
    logger.setLevel(verb_map[lvl])


def save_state():
    wb.config.setValue('geometry/size', wb.main_window.size())
    wb.config.setValue('geometry/position', wb.main_window.pos())
    wb.config.setValue('geometry/splitter_pos', wb.splitter.sizes())
    wb.config.setValue('geometry/job_view_header', wb.job_view.horizontalHeader().saveState())