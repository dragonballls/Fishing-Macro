"""Read-only zoom invariants and optional real-Tk integration checks.

Set BLOXFISH_TEST_GUI=1 to exercise real canvas events without game input.
Set BLOXFISH_TEST_SCREENSHOTS to a temporary directory for visual QA captures.
"""
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

from PIL import Image, ImageDraw
import customtkinter as ctk

from bloxfish.capture import Rect
from bloxfish.config import Config
from image_inspector import ImageViewport, viewport_image, ImageInspector
from easy_run import Calibrator, CALIB_GROUPS, _calib_image_path, _calib_image

REAL_SHOOT = Calibrator.shoot
REAL_CTK_COORDS = ctk.CTkCanvas.coords


class ViewportTests(unittest.TestCase):
    def test_zoom_preserves_the_pixel_under_pointer(self):
        view = ImageViewport(3840, 2160, 960, 540)
        view.fit()
        before = view.source_at(320, 210)
        for _ in range(8):
            view.zoom(1.2, 320, 210)
            after = view.source_at(320, 210)
            for expected, actual in zip(before, after):
                self.assertAlmostEqual(expected, actual)

    def test_clamps_fit_max_zoom_pan_and_resize(self):
        view = ImageViewport(1920, 1080, 960, 540)
        view.fit()
        view.zoom(1e8, 480, 270)
        self.assertEqual(view.scale, 8)
        view.x, view.y = -1e9, 1e9
        view.clamp()
        self.assertEqual(view.x, 960 - 1920 * 8)
        self.assertEqual(view.y, 0)
        view.zoom(1e-10, 480, 270)
        self.assertEqual(view.scale, .5)
        view.resize(480, 270)
        self.assertEqual(view.scale, .25)
        view.resize(800, 800)
        self.assertGreater(view.y, 0)

    def test_render_is_viewport_sized_and_source_is_unchanged(self):
        source = Image.new('RGB', (3840, 2160), '#f0a020')
        before = source.tobytes()
        view = ImageViewport(*source.size, 640, 360)
        view.fit()
        for _ in range(15):
            view.zoom(1.2, 320, 180)
            rendered = viewport_image(source, view)
            self.assertEqual(rendered.size, (640, 360))
            self.assertEqual(rendered.getpixel((320, 180)), (240, 160, 32))
        self.assertEqual(before, source.tobytes())

    def test_reference_resolution_uses_existing_slot_aliases(self):
        self.assertEqual(_calib_image_path('menu_item3').name, 'menu_item3.png')
        self.assertNotEqual(_calib_image_path('craft_button'), _calib_image_path('craft'))

    def test_portrait_reference_is_bounded_in_both_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'portrait.png'
            Image.new('RGB', (500, 3000)).save(path)
            with mock.patch('easy_run._calib_image_path', return_value=path):
                for width, height in ((230, 180), (420, 220), (420, 180)):
                    rendered = _calib_image('portrait', width, height)
                    rw, rh = rendered.cget('size')
                    self.assertLessEqual(rw, width)
                    self.assertEqual(rh, height)


@unittest.skipUnless(os.environ.get('BLOXFISH_TEST_GUI') == '1', 'opt-in real Tk UI test')
class InspectorUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.capture_patch = mock.patch.object(Calibrator, 'shoot', lambda _view: None)
        self.capture_patch.start()
        self.cfg = Config()
        self.cal = Calibrator(self.root, self.cfg)
        self.cal.win = Rect(-1920, 40, 1920, 1080)
        self.cal.found = True
        self.cal._shot = Image.new('RGB', (1920, 1080), '#172d43')
        draw = ImageDraw.Draw(self.cal._shot)
        for x in range(0, 1920, 80):
            draw.line((x, 0, x, 1080), fill='#244762')
        for y in range(0, 1080, 80):
            draw.line((0, y, 1920, y), fill='#244762')
        draw.rectangle((480, 480, 1440, 580), fill='#111b24', outline='#67d9af', width=4)
        draw.rectangle((660, 485, 910, 550), fill='#53b991')
        draw.text((490, 600), 'Synthetic calibration fixture - no game capture', fill='white')
        self.cal.zoom_shot_btn.configure(state='normal')
        self.pump()
        self.cal._fit()

    def pump(self):
        self.root.update()
        time.sleep(.04)
        self.root.update()

    def tearDown(self):
        if self.cal.winfo_exists():
            self.cal.destroy()
        self.pump()
        self.capture_patch.stop()
        self.assertEqual(self.errors, [])

    def test_parent_close_cancels_pending_inspector_render(self):
        self.cal._inspect_screenshot()
        viewer = self.cal._inspector
        viewer._zoom(1.2)
        self.assertIsNotNone(viewer._pending)
        self.cal.destroy()
        self.assertTrue(viewer._closed)
        self.assertIsNone(viewer._pending)
        self.pump()

    def test_issue49_reproduces_on_internal_canvas_with_522_coords(self):
        """CTk 5.2.2 performs the operation but does not return its result."""
        cal = self.cal
        cal.select('menu')
        native = cal.canvas
        internal = ctk.CTkCanvas(cal.canvas_shell)
        shape = cal.shapes['menu']
        before_shape = dict(shape)
        rectangle = internal.create_rectangle(10, 20, 120, 90)
        grip = internal.create_rectangle(106, 76, 120, 90)

        def released_coords(canvas, item, *values):
            REAL_CTK_COORDS(canvas, item, *values)
            # Deliberately no return, exactly like the v5.2.2 source.

        try:
            cal.canvas = internal
            shape.update(id=rectangle, grips={'corner': grip})
            with mock.patch.object(ctk.CTkCanvas, 'coords', released_coords):
                with self.assertRaisesRegex(TypeError, 'NoneType'):
                    cal._hover(SimpleNamespace(x=115, y=83))
                with self.assertRaisesRegex(TypeError, 'NoneType'):
                    cal._down(SimpleNamespace(x=50, y=50))
        finally:
            cal.canvas = native
            shape.clear()
            shape.update(before_shape)
            internal.destroy()

    def test_all_controls_drag_resize_and_reload_with_522_internal_canvas(self):
        cal = self.cal
        self.assertIs(type(cal.canvas), tk.Canvas)

        def released_coords(canvas, item, *values):
            REAL_CTK_COORDS(canvas, item, *values)

        with mock.patch.object(ctk.CTkCanvas, 'coords', released_coords):
            for width, height in ((900, 520), (1000, 680), (1440, 900)):
                cal.geometry(f'{width}x{height}+0+0')
                cal.workspace._parent_canvas.yview_moveto(0)
                self.pump()
                for _, _, _, entries in CALIB_GROUPS:
                    for entry in entries:
                        key, kind, holder, fields = entry[:4]
                        with self.subTest(size=(width, height), key=key):
                            cal.select(key)
                            self.pump()
                            # Stable synthetic positions keep every control
                            # inside the image at every tested window size.
                            obj = getattr(self.cfg, holder)
                            if kind == 'box':
                                for field, value in zip(fields, (.12, .14, .46, .48)):
                                    setattr(obj, field, value)
                            else:
                                setattr(obj, fields[0], (.3, .3))
                            cal.redraw()
                            before = cal._fracs(entry)
                            item = cal.shapes[key]
                            x0, y0, x1, y1 = cal.canvas.coords(item['id'])
                            x, y = int((x0 + x1) / 2), int((y0 + y1) / 2)
                            cal.canvas.event_generate('<Motion>', x=x, y=y)
                            self.assertEqual(cal.canvas.cget('cursor'), 'fleur')
                            cal.canvas.event_generate('<Button-1>', x=x, y=y)
                            self.assertIsNotNone(cal.drag)
                            cal.canvas.event_generate('<B1-Motion>', x=x + 9, y=y + 7)
                            cal.canvas.event_generate('<ButtonRelease-1>', x=x + 9, y=y + 7)
                            moved = cal._fracs(entry)
                            self.assertNotEqual(moved, before)
                            self.assertIsNone(cal.drag)
                            self.assertIn(key, cal._reviewed)
                            if kind == 'box':
                                gx0, gy0, gx1, gy1 = cal.canvas.coords(item['grips']['corner'])
                                gx, gy = int((gx0 + gx1) / 2), int((gy0 + gy1) / 2)
                                cal.canvas.event_generate('<Motion>', x=gx, y=gy)
                                self.assertEqual(cal.canvas.cget('cursor'), 'sizing')
                                cal.canvas.event_generate('<Button-1>', x=gx, y=gy)
                                self.assertEqual(cal.drag[0], 'corner')
                                cal.canvas.event_generate('<B1-Motion>', x=gx + 11, y=gy + 9)
                                cal.canvas.event_generate('<ButtonRelease-1>', x=gx + 11, y=gy + 9)
                                resized = cal._fracs(entry)
                                self.assertGreater(resized[-1], moved[-1])
                                if len(fields) == 4:
                                    self.assertGreater(resized[2], moved[2])
                            self.assertEqual(self.errors, [])
                            # Projected outlines remain the engine's exact
                            # geometry, not a CTk DPI-adjusted approximation.
                            coords = cal.canvas.coords(item['id'])
                            if kind == 'box':
                                self.assertEqual(tuple(coords), cal._box_px(*cal._fracs(entry)))
                            else:
                                for actual, expected in zip(
                                        ((coords[0] + coords[2]) / 2,
                                         (coords[1] + coords[3]) / 2),
                                        cal._dot_px(*cal._fracs(entry))):
                                    self.assertAlmostEqual(actual, expected)
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            real_save = Config.save
            with mock.patch.object(Config, 'save', autospec=True,
                                   side_effect=lambda cfg: real_save(cfg, config)) as save:
                cal.save()
                save.assert_called_once_with(self.cfg)
            loaded = Config.load(config)
            self.assertEqual(asdict(loaded), asdict(self.cfg))

    def test_resize_or_selection_cancels_old_drag_anchor(self):
        cal = self.cal
        cal.select('center')
        x, y = cal._dot_px(*self.cfg.shop.center)
        cal._down(SimpleNamespace(x=x, y=y))
        self.assertIsNotNone(cal.drag)
        before = asdict(self.cfg)
        cal.geometry('900x520')
        self.pump()
        self.assertIsNone(cal.drag)
        cal._move(SimpleNamespace(x=x + 50, y=y + 50))
        cal._up()
        self.assertEqual(asdict(self.cfg), before)
        cal._down(SimpleNamespace(x=cal._dot_px(*self.cfg.shop.center)[0],
                                  y=cal._dot_px(*self.cfg.shop.center)[1]))
        self.assertIsNotNone(cal.drag)
        cal.select('menu')
        cal._move(SimpleNamespace(x=200, y=200))
        cal._up()
        self.assertIsNone(cal.drag)
        self.assertEqual(asdict(self.cfg), before)

    def test_reshoot_closes_viewer_before_capture_and_preserves_reviews(self):
        import numpy as np
        cal = self.cal
        cal._record_review('bar_search')
        before = (asdict(self.cfg), cal._review_snapshot())
        cal._inspect_screenshot()
        viewer = cal._inspector
        screen = mock.Mock()

        def capture(_rect):
            self.assertTrue(viewer._closed)
            self.assertIsNone(cal._inspector)
            return np.zeros((1080, 1920, 3), dtype=np.uint8)

        screen.grab.side_effect = capture
        cal.drag = ('move', 20, 20)
        with mock.patch('bloxfish.capture.Screen', return_value=screen), \
                mock.patch('bloxfish.capture.find_game_window', return_value=(cal.win, True)), \
                mock.patch('easy_run.time.sleep'):
            REAL_SHOOT(cal)
        self.pump()
        self.assertIsNone(cal.drag)
        screen.close.assert_called_once()
        self.assertEqual(before, (asdict(self.cfg), cal._review_snapshot()))

    def capture(self, name, window):
        directory = os.environ.get('BLOXFISH_TEST_SCREENSHOTS')
        if directory:
            from PIL import ImageGrab
            window.deiconify()
            window.attributes('-topmost', True)
            window.lift()
            self.pump()
            time.sleep(.25)  # allow desktop compositor to display the QA window
            self.assertTrue(window.winfo_viewable())
            x, y = window.winfo_rootx(), window.winfo_rooty()
            image = ImageGrab.grab((x, y, x + window.winfo_width(), y + window.winfo_height()))
            image.save(Path(directory) / name)
            window.attributes('-topmost', False)

    def test_real_viewer_events_preserve_all_calibration_state(self):
        cal = self.cal
        for key in ('bar_search', 'center', 'fish_tpl', 'craft'):
            with self.subTest(key=key):
                if key in ('fish_tpl', 'craft'):
                    cal.select_color(key)
                else:
                    cal.select(key)
                self.pump()  # settle the guide's normal responsive layout first
                before = (asdict(self.cfg), cal.scale, cal._review_snapshot(),
                          cal._tpl_center, hashlib.sha256(cal._shot.tobytes()).digest())
                cal.zoom_shot_btn.invoke()
                self.pump()
                viewer = cal._inspector
                self.assertNotEqual(id(viewer.source), id(cal._shot))
                for delta in (120, 120, -120, 120):
                    viewer.canvas.event_generate('<MouseWheel>', delta=delta, x=250, y=160)
                viewer.canvas.event_generate('<Button-1>', x=250, y=160)
                viewer.canvas.event_generate('<B1-Motion>', x=220, y=130)
                viewer.canvas.event_generate('<ButtonRelease-1>', x=220, y=130)
                self.pump()
                self.assertIsNone(viewer._pending)  # no redraw timer while idle
                if key == 'bar_search':
                    self.capture('screenshot-zoom.png', viewer)
                viewer.geometry('640x440')
                self.pump()
                viewer._actual_size()
                viewer._fit_view()
                self.pump()
                viewer.destroy()
                self.assertEqual(before, (asdict(self.cfg), cal.scale, cal._review_snapshot(),
                                         cal._tpl_center, hashlib.sha256(cal._shot.tobytes()).digest()))
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            self.cfg.save(config)
            loaded = Config.load(config)
            self.assertEqual(loaded.shop.center, self.cfg.shop.center)
            self.assertEqual(loaded.detection.bar_search_left, self.cfg.detection.bar_search_left)

    def test_reference_original_pixels_compact_access_and_close_cleanup(self):
        cal = self.cal
        cal.select('craft_button')
        with Image.open(_calib_image_path('craft_button')) as source:
            expected = source.size
        cal.zoom_ref_btn.invoke()
        self.pump()
        viewer = cal._inspector
        self.assertEqual(viewer.source.size, expected)
        viewer._zoom(2)
        self.pump()
        self.capture('reference-zoom.png', viewer)
        viewer.canvas.event_generate('<Button-4>', x=240, y=130)
        viewer.canvas.event_generate('<Button-5>', x=240, y=130)
        viewer._zoom(1.2)
        self.assertIsNotNone(viewer._pending)
        cal._close_inspector()
        self.assertTrue(viewer._closed)
        self.assertIsNone(viewer._pending)
        self.pump()
        cal.geometry('1000x680')
        self.pump()
        self.assertTrue(cal.image_shell.winfo_ismapped())
        self.assertGreaterEqual(cal.canvas.winfo_height(), 330)
        self.assertTrue(cal.zoom_ref_btn.winfo_ismapped())
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        for button in descendants(cal):
            if isinstance(button, ctk.CTkButton) and button.cget('text') in (
                    'Save calibration', 'Re-shoot', 'Reset selected'):
                self.assertTrue(button.winfo_viewable())
                self.assertGreaterEqual(button.winfo_rootx(), cal.winfo_rootx())
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     cal.winfo_rootx() + cal.winfo_width())
        self.capture('calibration-compact.png', cal)
        cal.select_color('dialogue')  # slot may legitimately be absent
        with mock.patch('easy_run.Image.open', side_effect=OSError('missing image')):
            cal._inspect_reference()
        self.assertIsNone(cal._inspector)
        self.assertIn('could not be opened', cal._interaction)

    def test_workspace_resize_scroll_and_zoom_preserve_calibration(self):
        cal = self.cal
        cal.select('craft_button')
        cal._toggle_guide()
        before = (asdict(self.cfg), cal._review_snapshot(), cal.sel, cal.pick)
        for width, height in ((900, 520), (1000, 680), (1440, 900), (1440, 1000), (900, 520)):
            with self.subTest(size=(width, height)):
                cal.geometry(f'{width}x{height}+0+0')
                self.pump()
                self.assertGreaterEqual(cal.canvas.winfo_height(), 330)
                self.assertTrue(cal.image_shell.winfo_ismapped())
                for label in (cal.d_text, cal.d_avoid, cal.d_check):
                    self.assertTrue(label.winfo_ismapped())
                self.assertEqual(int(cal.image_shell.grid_info()['row']),
                                 10 if width < 1150 or height < 780 else 0)
                expected_height = max(380, min(560, height - 410))
                self.assertEqual(cal.canvas_shell.cget('height'), expected_height)
                self.assertTrue(cal._guide_expanded)
                scroll = cal.workspace._parent_canvas
                scroll.yview_moveto(0)
                self.pump()
                self.capture(f'layout-{width}x{height}-top.png', cal)
                cal.canvas.event_generate('<MouseWheel>', delta=-120, x=40, y=40)
                self.pump()
                self.assertGreater(scroll.yview()[0], 0)
                scroll.yview_moveto(1)
                self.pump()
                self.capture(f'layout-{width}x{height}-bottom.png', cal)
                for button in (cal.zoom_shot_btn, cal.zoom_ref_btn):
                    button.invoke()
                    self.pump()
                    self.assertFalse(cal._inspector._closed)
                    cal._close_inspector()
                self.assertEqual(before, (asdict(self.cfg), cal._review_snapshot(), cal.sel, cal.pick))


if __name__ == '__main__':
    unittest.main()
