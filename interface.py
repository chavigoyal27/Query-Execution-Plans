import os
import re
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# GUI colour palette
APP_BG, CARD, TEXT, BLACK = '#F4F5F7', '#FFFFFF', '#1F2937', '#111827'
MUTED, BORDER, HOVER, ZEBRA = '#6B7280', '#E5E7EB', '#F3F4F6', '#F9FAFB'
ACCENT, ACCENT_H, EDITOR_BG = '#3B5BDB', '#2F4AC0', '#FAFBFC'
CONNECTOR, SHADOW = '#B8BEC7', '#E3E7EC'
GREEN, ORANGE, RED = '#34A853', '#F29900', '#D93025'
# Visual styles for node comparison statuses
NODE_STYLES = {'same': {'fill': '#E6F4EA', 'border': GREEN, 'label': 'Matching'}, 'different': {'fill': '#FFF4E0', 'border': ORANGE, 'label': 'Different'}, 'unmatched': {'fill': '#FDE8E8', 'border': RED, 'label': 'Unmatched'}, 'uncertain': {'fill': '#ECEFF3', 'border': '#9AA3AF', 'label': 'Uncertain'}}
STATUS_ORDER = list(NODE_STYLES)
STATUS_MAP = {'unchanged': 'same', 'same': 'same', 'matching': 'same', 'changed': 'different', 'different': 'different', 'unmatched': 'unmatched', 'uncertain': 'uncertain', 'default': 'uncertain'}
# Default TPC-H Query 14
DEFAULT_SQL = """SELECT 100.00 * SUM(CASE
    WHEN p_type LIKE 'PROMO%'
    THEN l_extendedprice * (1 - l_discount)
    ELSE 0 END) / SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM lineitem, part
WHERE l_partkey = p_partkey
AND l_shipdate >= DATE '1993-11-01'
AND l_shipdate < DATE '1993-11-01' + INTERVAL '1' MONTH;"""
EMPTY_DETAILS = 'Select a node to view its properties.'
EMPTY_SUMMARY = 'Run a query to view the comparison results.'

# Reusable GUI helper functions
def label(parent, text, size=11, bold=False, color=TEXT, bg=CARD):
    return tk.Label(parent, text=text, bg=bg, fg=color, anchor='w', font=('Arial', size, 'bold' if bold else 'normal'))

def chip(parent, text, style, size=9, padx=10, pady=3):
    return tk.Label(parent, text=text, bg=style['fill'], fg=BLACK, font=('Arial', size, 'bold'), padx=padx, pady=pady, highlightbackground=style['border'], highlightthickness=1)

def link(parent, text, command, side='right', padx=(0, 16)):
    item = tk.Label(parent, text=text, bg=CARD, fg=ACCENT, font=('Arial', 10, 'bold'), cursor='hand2')
    item.pack(side=side, padx=padx)
    item.bind('<Button-1>', lambda event: command())
    return item

def card(parent):
    return tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)

def rule(parent, pady=(14, 14)):
    tk.Frame(parent, bg=BORDER, height=1).pack(fill='x', pady=pady)

def rounded_points(x1, y1, x2, y2, r):
    return [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2, x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]

def clear_frame(frame):
    for widget in frame.winfo_children(): widget.destroy()

def placeholder(frame, message):
    clear_frame(frame)
    label(frame, message, 10, color=MUTED).pack(anchor='w', pady=8)

# Convert backend explanations into user-friendly descriptions
def format_explanation(item):
    if isinstance(item, dict):
        item = item.get('explanation', str(item))
    text = str(item)
    # Replace internal source identifiers with display names
    text = re.sub(r'\bpostgresql\b', 'PostgreSQL', text, flags=re.IGNORECASE)
    text = re.sub(r'\bai\b', 'Google Gemini', text, flags=re.IGNORECASE)
    # Convert zero-based JSON paths into readable child positions
    def format_path(match):
        path = match.group(0)
        children = re.findall(r'\.Plans\[(\d+)\]', path)
        if not children:
            return 'Root'
        return 'Root → ' + ' → '.join(f'Child {int(index) + 1}' for index in children)
    text = re.sub(r'\broot(?:\.Plans\[\d+\])*', format_path, text)
    return text

# Retrieve PostgreSQL and Gemini plans, then compare their structures
def execute_comparison(sql, schema):
    from preprocessing import connect_database, get_postgresql_plan, get_ai_query_execution_plan
    from comparison import compare_plans
    sql = sql.strip()
    if not sql: raise ValueError('Please enter an SQL query.')
    # Read PostgreSQL connection settings from environment variables
    config = {'host': os.getenv('PGHOST', 'localhost'), 'port': int(os.getenv('PGPORT', '5432')), 'dbname': os.getenv('PGDATABASE', 'TPC-H'), 'user': os.getenv('PGUSER', 'postgres'), 'password': os.getenv('PGPASSWORD', ''), 'connect_timeout': 5}
    with connect_database(config) as connection:
        pg_plan = get_postgresql_plan(connection, sql, schema)
    ai_plan = get_ai_query_execution_plan(sql)
    # Preserve both plan structures for the comparison algorithm
    result = compare_plans(pg_plan, ai_plan)
    if result.get('mode') != 'tree': raise ValueError('The comparison backend did not return a tree result.')
    return result

# Custom rounded button with hover and disabled states
class RoundedButton(tk.Canvas):
    def __init__(self, parent, text, command, primary=False, width=120, height=36):
        super().__init__(parent, width=width, height=height, bg=parent.cget('bg'), highlightthickness=0, bd=0, cursor='hand2')
        self.text, self.command, self.primary = text, command, primary
        self.w, self.h, self.enabled = width, height, True
        self.bind('<Enter>', lambda e: self.enabled and self.draw(True))
        self.bind('<Leave>', lambda e: self.draw())
        self.bind('<Button-1>', lambda e: self.enabled and self.command())
        self.draw()

    def draw(self, hover=False):
        self.delete('all')
        if not self.enabled: fill, fg, outline = BORDER, MUTED, BORDER
        elif self.primary:
            fill = ACCENT_H if hover else ACCENT
            fg, outline = CARD, fill
        else: fill, fg, outline = (HOVER if hover else CARD), TEXT, BORDER
        self.create_polygon(rounded_points(1, 1, self.w-1, self.h-1, 7), smooth=True, splinesteps=12, fill=fill, outline=outline)
        self.create_text(self.w/2, self.h/2, text=self.text, fill=fg, font=('Arial', 10, 'bold'))

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.configure(cursor='hand2' if enabled else 'arrow')
        self.draw()

# Scrollable container for details and comparison summaries
class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg=CARD):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg, padx=22, pady=18)
        window = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.bind_all('<MouseWheel>', self.on_wheel, add='+')

    def on_wheel(self, event):
        try: widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError): return
        while widget is not None and widget is not self: widget = widget.master
        if widget is None or self.inner.winfo_reqheight() <= self.canvas.winfo_height(): return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

# Tab navigation between node details and comparison results
class TabView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=CARD)
        self.bar = tk.Frame(self, bg=CARD)
        self.bar.pack(fill='x', padx=10)
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')
        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill='both', expand=True)
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)
        self.tabs, self.current = {}, None

    def add(self, key, text):
        page = ScrollFrame(self.body)
        page.grid(row=0, column=0, sticky='nsew')
        cell = tk.Frame(self.bar, bg=CARD)
        cell.pack(side='left', padx=(0, 8))
        tab = tk.Label(cell, text=text, bg=CARD, fg=MUTED, padx=16, pady=11, font=('Arial', 10, 'bold'), cursor='hand2')
        tab.pack()
        underline = tk.Frame(cell, bg=CARD, height=3)
        underline.pack(fill='x')
        for widget in (cell, tab, underline): widget.bind('<Button-1>', lambda e, k=key: self.select(k))
        tab.bind('<Enter>', lambda e, k=key: k != self.current and tab.configure(fg=TEXT))
        tab.bind('<Leave>', lambda e, k=key: k != self.current and tab.configure(fg=MUTED))
        self.tabs[key] = (tab, underline, page)
        if self.current is None: self.select(key)
        return page.inner

    def select(self, key):
        for name, (tab, underline, _) in self.tabs.items():
            tab.configure(fg=ACCENT if name == key else MUTED)
            underline.configure(bg=ACCENT if name == key else CARD)
        self.tabs[key][2].tkraise()
        self.current = key

# Interactive execution plan tree supporting selection, zoom and pan
class PlanCanvas(tk.Frame):
    NODE_W, NODE_H, GAP_X, GAP_Y = 240, 90, 50, 80

    def __init__(self, parent, title=''):
        super().__init__(parent, bg=CARD)
        self.on_select = None
        self.zoom_level = 1.0
        self.statuses, self.node_rects, self.text_items = {}, {}, []
        self.tree_data = self.selected_id = None
        bar = tk.Frame(self, bg=CARD)
        bar.pack(fill='x', pady=(0, 8))
        tk.Label(bar, text=title, bg=CARD, fg=BLACK, font=('Arial', 12, 'bold')).pack(side='left')
        for text, command in [('Reset', self.reset), ('Fit', self.fit), ('+', lambda: self.zoom(1.2)), ('−', lambda: self.zoom(0.8))]:
            RoundedButton(bar, text, command, width=54, height=28).pack(side='right', padx=(6, 0))
        self.canvas = tk.Canvas(self, bg=CARD, highlightthickness=0, height=200)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind('<B1-Motion>', lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind('<MouseWheel>', lambda e: self.scroll(e, 'y'))
        self.canvas.bind('<Shift-MouseWheel>', lambda e: self.scroll(e, 'x'))
        for sequence in ('<Control-MouseWheel>', '<Command-MouseWheel>'): self.canvas.bind(sequence, self.mouse_zoom)
        self.show_empty()

    def show_empty(self):
        self.tree_data = self.selected_id = None
        self.node_rects, self.text_items = {}, []
        self.canvas.delete('all')
        self.canvas.create_text(15, 20, anchor='nw', text='No execution plan to display', fill=MUTED, font=('Arial', 11))

    def scroll(self, event, axis):
        if self.tree_data:
            view = self.canvas.yview_scroll if axis == 'y' else self.canvas.xview_scroll
            view(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def mouse_zoom(self, event):
        self.zoom(1.2 if event.delta > 0 else 0.8)
        return 'break'

    # Scale tree elements while preserving their relative positions
    def zoom(self, factor):
        new_zoom = self.zoom_level * factor
        if not 0.4 <= new_zoom <= 2.5: return
        self.canvas.scale('all', 0, 0, factor, factor)
        self.zoom_level = new_zoom
        for item, size, weight in self.text_items: self.canvas.itemconfigure(item, font=('Arial', max(6, round(size * new_zoom)), weight))
        self.update_bounds()

    def update_bounds(self):
        box = self.canvas.bbox('all')
        if box: self.canvas.configure(scrollregion=(box[0]-40, box[1]-40, box[2]+40, box[3]+40))

    def reset(self):
        if self.tree_data: self.draw(self.tree_data, self.statuses)

    # Adjust zoom to fit the execution plan within the visible canvas
    def fit(self):
        if not self.tree_data: return
        selected = self.selected_id
        if self.zoom_level != 1.0: self.draw(self.tree_data, self.statuses)
        self.canvas.update_idletasks()
        box = self.canvas.bbox('all')
        if box:
            factor = min(1.0, max(self.canvas.winfo_width(), 1)/(box[2]-box[0]+60), max(self.canvas.winfo_height(), 1)/(box[3]-box[1]+60))
            if factor < 1.0: self.zoom(max(factor, 0.4))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.highlight(selected)

    def highlight(self, node_id):
        if self.selected_id in self.node_rects:
            rect, border = self.node_rects[self.selected_id]
            self.canvas.itemconfigure(rect, outline=border, width=1.5)
        self.selected_id = None
        if node_id in self.node_rects:
            self.canvas.itemconfigure(self.node_rects[node_id][0], outline=ACCENT, width=3)
            self.canvas.tag_raise(f'node_{node_id}')
            self.selected_id = node_id

    def select_node(self, node_id, node, status):
        self.highlight(node_id)
        if self.on_select: self.on_select(node, status)

    def add_text(self, x, y, text, color, size, weight):
        item = self.canvas.create_text(x, y, anchor='w', text=text, fill=color, font=('Arial', size, weight))
        self.text_items.append((item, size, weight))
        return item

    def box(self, x, y, **kwargs):
        return self.canvas.create_polygon(rounded_points(x, y, x+self.NODE_W, y+self.NODE_H, 10), smooth=True, splinesteps=12, **kwargs)

    # Render the execution plan as a hierarchical tree
    def draw(self, tree, statuses):
        self.tree_data, self.statuses, self.zoom_level = tree, statuses, 1.0
        self.node_rects, self.text_items, self.selected_id = {}, [], None
        self.canvas.delete('all')
        nodes = {node['id']: node for node in tree['nodes']}
        widths = {}

        # Calculate the horizontal space required by each subtree
        def measure(node_id):
            if node_id not in widths:
                kids = nodes[node_id].get('children', [])
                total = sum(measure(k) for k in kids) + self.GAP_X * max(len(kids)-1, 0)
                widths[node_id] = max(self.NODE_W, total)
            return widths[node_id]

        # Recursively position nodes and draw their connections
        def render(node_id, left, y):
            node = nodes[node_id]
            x = left + (measure(node_id)-self.NODE_W)/2
            child_left, child_y = left, y+self.NODE_H+self.GAP_Y
            mid_y = y+self.NODE_H+self.GAP_Y/2
            for child_id in node.get('children', []):
                child_x = child_left+(measure(child_id)-self.NODE_W)/2
                self.canvas.create_line(x+self.NODE_W/2, y+self.NODE_H, x+self.NODE_W/2, mid_y, child_x+self.NODE_W/2, mid_y, child_x+self.NODE_W/2, child_y, fill=CONNECTOR, width=1.5)
                render(child_id, child_left, child_y)
                child_left += measure(child_id)+self.GAP_X
            # Colour each node according to its comparison status
            status = STATUS_MAP.get(statuses.get(node_id, 'uncertain'), 'uncertain')
            style = NODE_STYLES[status]
            shadow = self.box(x+2, y+3, fill=SHADOW, outline='')
            rect = self.box(x, y, fill=style['fill'], outline=style['border'], width=1.5)
            relation = str((node.get('attributes') or {}).get('Relation Name', ''))
            word = style['label'].lower()
            subtitle = f'{relation[:16]} · {word}' if relation else word
            items = [shadow, rect, self.add_text(x+14, y+24, str(node.get('operator', 'Unknown'))[:24], BLACK, 11, 'bold'), self.add_text(x+14, y+49, subtitle, MUTED, 10, 'normal')]
            self.node_rects[node_id] = (rect, style['border'])
            tag = f'node_{node_id}'
            for item in items: self.canvas.addtag_withtag(tag, item)
            self.canvas.tag_bind(tag, '<Button-1>', lambda e, n=node, s=status, i=node_id: self.select_node(i, n, s))
            self.canvas.tag_bind(tag, '<Enter>', lambda e: self.canvas.configure(cursor='hand2'))
            self.canvas.tag_bind(tag, '<Leave>', lambda e: self.canvas.configure(cursor=''))
        render(tree['root_id'], 30, 30)
        self.update_bounds()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

# Main application window for SQL input and QEP comparison
class QEPComparisonGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Query Execution Plan Comparison')
        self.geometry('1360x880')
        self.minsize(1000, 700)
        self.configure(bg=APP_BG)
        # Queue transfers worker results safely to Tkinter's main thread
        self.events = queue.Queue()
        self.request_id = 0
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Minimal.TEntry', padding=7, fieldbackground=CARD, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.configure('Accent.Horizontal.TProgressbar', troughcolor=BORDER, background=ACCENT, bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
        self.build_header()
        self.build_sql_card()
        self.build_workspace()
        for sequence in ('<Control-Return>', '<Command-Return>'): self.bind(sequence, self.on_shortcut)
        self.after(100, self.check_results)

    # Build the header, database settings and action buttons
    def build_header(self):
        header = tk.Frame(self, bg=APP_BG)
        header.pack(fill='x', padx=24, pady=(18, 10))
        tk.Label(header, text='Q', bg=ACCENT, fg=CARD, font=('Arial', 16, 'bold'), width=2).pack(side='left', padx=(0, 14))
        left = tk.Frame(header, bg=APP_BG)
        left.pack(side='left')
        label(left, 'QUERY EXECUTION PLAN COMPARISON', 16, True, BLACK, APP_BG).pack(anchor='w')
        row = tk.Frame(left, bg=APP_BG)
        row.pack(anchor='w', pady=(3, 0))
        self.status_dot = tk.Label(row, text='●', bg=APP_BG, fg=GREEN, font=('Arial', 9))
        self.status_dot.pack(side='left', padx=(0, 6))
        self.status = label(row, 'Ready', 10, color=MUTED, bg=APP_BG)
        self.status.pack(side='left')
        self.progress = ttk.Progressbar(row, mode='indeterminate', length=110, style='Accent.Horizontal.TProgressbar')
        controls = tk.Frame(header, bg=APP_BG)
        controls.pack(side='right')
        self.compare_button = RoundedButton(controls, 'Compare Plans', self.compare, primary=True, width=140)
        self.compare_button.pack(side='right')
        RoundedButton(controls, 'Clear', self.clear, width=80).pack(side='right', padx=(0, 10))
        self.schema = tk.StringVar(value='public')
        ttk.Entry(controls, textvariable=self.schema, width=12, style='Minimal.TEntry').pack(side='right', padx=(0, 12))
        label(controls, 'Schema', 10, color=MUTED, bg=APP_BG).pack(side='right', padx=(0, 6))
        self.database = tk.StringVar(value=os.getenv('PGDATABASE', 'TPC-H'))
        ttk.Entry(controls, textvariable=self.database, width=12, style='Minimal.TEntry', state='readonly').pack(side='right', padx=(0, 16))
        label(controls, 'Database', 10, color=MUTED, bg=APP_BG).pack(side='right', padx=(0, 8))

    # Create the SQL editor with scrolling and undo/redo functionality
    def build_sql_card(self):
        sql_card = card(self)
        sql_card.pack(fill='x', padx=24)
        top = tk.Frame(sql_card, bg=CARD)
        top.pack(fill='x', padx=16, pady=(12, 8))
        label(top, 'SQL Query', 12, True, BLACK).pack(side='left')
        label(top, 'Ctrl / ⌘ + Enter to compare', 9, color=MUTED).pack(side='left', padx=(14, 0))
        self.sql_visible = True
        self.sql_toggle = link(top, 'Hide', self.toggle_sql, padx=0)
        link(top, 'Redo', self.sql_redo)
        link(top, 'Undo', self.sql_undo)
        self.sql_frame = tk.Frame(sql_card, bg=CARD)
        self.sql_frame.pack(fill='x', padx=16, pady=(0, 14))
        self.sql = tk.Text(self.sql_frame, height=5, wrap='word', font=('Menlo', 11), bg=EDITOR_BG, fg=BLACK, insertbackground=BLACK, relief='flat', bd=0, highlightthickness=0, padx=12, pady=10, undo=True, autoseparators=True, maxundo=-1)
        sql_scrollbar = ttk.Scrollbar(self.sql_frame, orient='vertical', command=self.sql.yview)
        self.sql.configure(yscrollcommand=sql_scrollbar.set)
        sql_scrollbar.pack(side='right', fill='y')
        self.sql.pack(side='left', fill='both', expand=True)
        # Populate the editor with the default TPC-H query
        self.sql.insert('1.0', DEFAULT_SQL)
        self.sql.bind('<Control-y>', lambda e: (self.sql_redo(), 'break')[1])
        for sequence in ('<Control-Return>', '<Command-Return>'): self.sql.bind(sequence, self.on_shortcut)

    # Arrange both execution plan trees above the comparison results
    def build_workspace(self):
        pane = tk.PanedWindow(self, orient='vertical', bg=APP_BG, bd=0, sashwidth=10, sashrelief='flat', opaqueresize=True)
        pane.pack(fill='both', expand=True, padx=24, pady=(12, 20))
        trees = card(pane)
        head = tk.Frame(trees, bg=CARD)
        head.pack(fill='x', padx=16, pady=(12, 6))
        label(head, 'Execution Plans', 12, True, BLACK).pack(side='left')
        label(head, 'Click a node to inspect it. Drag to pan, Ctrl + scroll to zoom.', 10, color=MUTED).pack(side='left', padx=(14, 0))
        # Display the node comparison status legend
        for key in reversed(STATUS_ORDER):
            style = NODE_STYLES[key]
            item = tk.Frame(head, bg=CARD)
            item.pack(side='right', padx=(16, 0))
            tk.Frame(item, bg=style['fill'], width=14, height=14, highlightbackground=style['border'], highlightthickness=1).pack(side='left', padx=(0, 6))
            label(item, style['label'], 10, color=MUTED).pack(side='left')
        plans = tk.PanedWindow(trees, orient='horizontal', bg=CARD, bd=0, sashwidth=8, sashrelief='flat', opaqueresize=True)
        plans.pack(fill='both', expand=True, padx=16, pady=(0, 14))
        views = []
        for title in ('PostgreSQL', 'Google Gemini'):
            view = PlanCanvas(plans, title)
            plans.add(view, minsize=250, stretch='always')
            view.on_select = lambda node, status, t=title, v=view: self.on_node_selected(t, v, node, status)
            views.append(view)
        self.pg_view, self.ai_view = views
        pane.add(trees, minsize=260, stretch='always')
        bottom = card(pane)
        self.tabs = TabView(bottom)
        self.tabs.pack(fill='both', expand=True)
        self.details_frame = self.tabs.add('details', 'Node Details')
        self.summary_frame = self.tabs.add('summary', 'Comparison Summary')
        placeholder(self.details_frame, EMPTY_DETAILS)
        placeholder(self.summary_frame, EMPTY_SUMMARY)
        self.tabs.select('summary')
        pane.add(bottom, minsize=160, height=300, stretch='never')

    def sql_undo(self):
        try: self.sql.edit_undo()
        except tk.TclError: pass

    def sql_redo(self):
        try: self.sql.edit_redo()
        except tk.TclError: pass

    def toggle_sql(self):
        if self.sql_visible: self.sql_frame.pack_forget()
        else: self.sql_frame.pack(fill='x', padx=16, pady=(0, 14))
        self.sql_visible = not self.sql_visible
        self.sql_toggle.configure(text='Hide' if self.sql_visible else 'Show')

    def on_shortcut(self, event):
        self.compare()
        return 'break'

    # Update the application status and progress indicator
    def set_status(self, text, kind='ready'):
        self.status_dot.configure(fg={'ready': GREEN, 'busy': ORANGE, 'error': RED}[kind])
        self.status.configure(text=text)
        if kind == 'busy':
            self.progress.pack(side='left', padx=(14, 0))
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def detail_row(self, key, value, shade):
        bg = ZEBRA if shade else CARD
        row = tk.Frame(self.details_frame, bg=bg)
        row.pack(fill='x')
        row.grid_columnconfigure(1, weight=1)
        tk.Label(row, text=str(key), bg=bg, fg=MUTED, font=('Arial', 10), anchor='nw', width=22).grid(row=0, column=0, sticky='nw', padx=(10, 0), pady=7)
        tk.Label(row, text=str(value), bg=bg, fg=BLACK, font=('Arial', 10), anchor='nw', justify='left', wraplength=800).grid(row=0, column=1, sticky='ew', padx=(0, 10), pady=7)

    def summary_tile(self, parent, number, text, style):
        tile = tk.Frame(parent, bg=style['fill'], highlightbackground=style['border'], highlightthickness=1)
        tile.pack(fill='x', pady=5)
        tk.Label(tile, text=str(number), bg=style['border'], fg=CARD, font=('Arial', 9, 'bold'), width=2).pack(side='left', anchor='n', padx=10, pady=10)
        body = tk.Label(tile, text=str(text), bg=style['fill'], fg=TEXT, font=('Arial', 10), justify='left', anchor='w', wraplength=380)
        body.pack(side='left', fill='x', expand=True, padx=(0, 12), pady=10)
        tile.bind('<Configure>', lambda e: body.configure(wraplength=max(e.width-80, 140)))

    # Display the selected node's properties in the Node Details tab
    def on_node_selected(self, source, owner, node, status):
        for view in (self.pg_view, self.ai_view):
            if view is not owner: view.highlight(None)
        self.show_node_details(source, node, status)
        self.tabs.select('details')

    def show_node_details(self, source, node, status):
        clear_frame(self.details_frame)
        attributes = node.get('attributes') or {}
        style = NODE_STYLES.get(STATUS_MAP.get(status, status), NODE_STYLES['uncertain'])
        head = tk.Frame(self.details_frame, bg=CARD)
        head.pack(fill='x', pady=(0, 6))
        label(head, str(node.get('operator', 'Unknown')), 13, True, BLACK).pack(side='left')
        chip(head, style['label'], style).pack(side='left', padx=(12, 0))
        tk.Label(head, text=source, bg=HOVER, fg=MUTED, font=('Arial', 9, 'bold'), padx=10, pady=3).pack(side='left', padx=(8, 0))
        rule(self.details_frame, (8, 10))
        rows = [('Source', source), ('Comparison Status', style['label'])]
        for index, (key, value) in enumerate(rows + list(attributes.items())): self.detail_row(key, value, index % 2 == 0)
        if not attributes: label(self.details_frame, 'No additional attributes available.', 10, color=MUTED).pack(anchor='w', pady=(12, 0))

    # Reset the application and restore the default SQL query
    def clear(self):
        self.request_id += 1
        self.compare_button.set_enabled(True)
        self.sql.edit_separator()
        self.sql.delete('1.0', 'end')
        self.sql.insert('1.0', DEFAULT_SQL)
        self.sql.edit_separator()
        self.pg_view.show_empty()
        self.ai_view.show_empty()
        placeholder(self.details_frame, EMPTY_DETAILS)
        placeholder(self.summary_frame, EMPTY_SUMMARY)
        self.set_status('Ready')

    # Run comparisons in a background thread to keep the GUI responsive
    def compare(self):
        if not self.compare_button.enabled: return
        sql = self.sql.get('1.0', 'end-1c').strip()
        schema = self.schema.get().strip() or 'public'
        if not sql:
            messagebox.showwarning('Missing Query', 'Please enter an SQL query.')
            return
        self.request_id += 1
        request_id = self.request_id
        self.compare_button.set_enabled(False)
        self.set_status('Generating execution plans...', 'busy')
        placeholder(self.summary_frame, 'Processing comparison. Please wait...')
        self.tabs.select('summary')
        # Execute database and Gemini operations outside the main GUI thread
        def task():
            try: self.events.put((request_id, 'success', execute_comparison(sql, schema)))
            except Exception as exc: self.events.put((request_id, 'error', f'{type(exc).__name__}: {exc}'))
        threading.Thread(target=task, daemon=True).start()

    # Process completed background tasks on Tkinter's main thread
    def check_results(self):
        try:
            while True:
                request_id, kind, value = self.events.get_nowait()
                # Ignore outdated results after Clear or a newer comparison
                if request_id != self.request_id: continue
                self.compare_button.set_enabled(True)
                if kind == 'error':
                    self.set_status('Comparison failed', 'error')
                    placeholder(self.summary_frame, value)
                    messagebox.showerror('Comparison Error', value)
                    continue
                try: self.display_results(value)
                except Exception as exc:
                    self.set_status('Display failed', 'error')
                    messagebox.showerror('Display Error', str(exc))
        except queue.Empty: pass
        self.after(100, self.check_results)

    # Display execution trees, node statuses and comparison statistics
    def display_results(self, result):
        annotations = result.get('node_annotations') or []
        breakdown = {}
        # Apply comparison statuses to both execution plan trees
        for source, view in (('postgresql', self.pg_view), ('ai', self.ai_view)):
            statuses = {a['node_id']: a['status'] for a in annotations if a.get('source') == source}
            tree = result['trees'][source]
            view.draw(tree, statuses)
            view.after(80, view.fit)
            # Count nodes in each comparison status category
            counts = dict.fromkeys(STATUS_ORDER, 0)
            for node in tree['nodes']: counts[STATUS_MAP.get(statuses.get(node['id'], 'uncertain'), 'uncertain')] += 1
            breakdown[source] = counts
        placeholder(self.details_frame, EMPTY_DETAILS)
        clear_frame(self.summary_frame)
        frame = self.summary_frame
        differences = result.get('differences') or []
        explanations = result.get('explanations') or []
        similarities = result.get('similarities') or []
        # Format the difference rate returned by comparison.py
        rate, rate_value = result.get('difference_rate'), None
        if rate is None: rate_text = 'Unavailable'
        else:
            try:
                rate_value = float(rate)
                rate_text = f'{rate_value:.1%}'
            except (TypeError, ValueError): rate_text = str(rate)
        stats = tk.Frame(frame, bg=CARD)
        stats.pack(fill='x', pady=(0, 14))
        def stat_tile(title, value, color=BLACK):
            tile = tk.Frame(stats, bg=APP_BG, padx=18, pady=12)
            tile.pack(side='left', fill='y', padx=(0, 12))
            label(tile, title, 10, color=MUTED, bg=APP_BG).pack(anchor='w')
            label(tile, value, 22, True, color, APP_BG).pack(anchor='w', pady=(2, 0))
            return tile
        # Display the overall comparison statistics
        tile = stat_tile('Difference rate', rate_text)
        if rate_value is not None:
            bar = tk.Canvas(tile, width=190, height=8, bg=APP_BG, highlightthickness=0)
            bar.pack(anchor='w', pady=(8, 0))
            bar.create_rectangle(0, 0, 190, 8, fill=BORDER, outline='')
            if rate_value > 0: bar.create_rectangle(0, 0, 190*min(rate_value, 1.0), 8, fill=ORANGE, outline='')
        stat_tile('Differences', str(len(differences)), ORANGE)
        stat_tile('Similarities', str(len(similarities)), GREEN)
        # Display node status counts for PostgreSQL and Gemini
        for name, source in (('PostgreSQL', 'postgresql'), ('Google Gemini', 'ai')):
            row = tk.Frame(frame, bg=CARD)
            row.pack(fill='x', pady=3)
            label(row, f'{name} nodes', 10, True, MUTED).pack(side='left', padx=(0, 12))
            for key in STATUS_ORDER:
                if breakdown[source][key]:
                    style = NODE_STYLES[key]
                    chip(row, f"{breakdown[source][key]} {style['label'].lower()}", style).pack(side='left', padx=(0, 8))
        rule(frame, (14, 16))
        columns = tk.Frame(frame, bg=CARD)
        columns.pack(fill='x')
        summary_items = explanations if differences else []
        # Display differences and similarities using readable source names and paths
        for index, (title, items, empty, key) in enumerate((('Differences', summary_items, 'No differences reported.', 'different'), ('Similarities', similarities, 'No similarities reported.', 'same'))):
            style = NODE_STYLES[key]
            columns.grid_columnconfigure(index, weight=1, uniform='summary')
            column = tk.Frame(columns, bg=CARD)
            column.grid(row=0, column=index, sticky='new', padx=(0, 12) if index == 0 else (12, 0))
            head = tk.Frame(column, bg=CARD)
            head.pack(fill='x', pady=(0, 6))
            label(head, title, 12, True, BLACK).pack(side='left')
            chip(head, str(len(items)), style, padx=8, pady=1).pack(side='left', padx=(10, 0))
            for number, item in enumerate(items, start=1):
                self.summary_tile(column, number, format_explanation(item), style)
            if not items: label(column, empty, 10, color=MUTED).pack(anchor='w')
        self.tabs.select('summary')
        self.set_status('Comparison complete')