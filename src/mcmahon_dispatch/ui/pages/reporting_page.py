from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from mcmahon_dispatch.services.reporting_service import ReportData, ReportingService, money


class LineChart(QWidget):
    def __init__(self) -> None:
        super().__init__(); self.setMinimumHeight(240); self._data=[]; self._mode='revenue'
    def set_data(self, rows, mode:str) -> None:
        self._data=list(rows); self._mode=mode; self.update()
    def paintEvent(self,event) -> None:
        super().paintEvent(event); p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=self.rect().adjusted(50,20,-20,-35); p.setPen(QPen(Qt.GlobalColor.gray,1)); p.drawRect(rect)
        values=[getattr(r,f'{self._mode}_cents')/100 for r in self._data]
        if not values: p.drawText(rect,Qt.AlignmentFlag.AlignCenter,'No report data for this period'); return
        top=max(max(values),1); points=[]
        for i,v in enumerate(values):
            x=rect.left()+(rect.width()*i/max(1,len(values)-1)); y=rect.bottom()-(rect.height()*v/top); points.append(QPointF(x,y))
        p.setPen(QPen(Qt.GlobalColor.darkYellow,3));
        for a,b in zip(points,points[1:]): p.drawLine(a,b)
        p.setPen(QPen(Qt.GlobalColor.gray,1))
        for point,row in zip(points,self._data): p.drawEllipse(point,3,3); p.drawText(int(point.x()-24),rect.bottom()+18,48,16,Qt.AlignmentFlag.AlignCenter,row.period[5:] if len(row.period)>=7 else row.period)


class MetricCard(QFrame):
    def __init__(self,title:str) -> None:
        super().__init__(); self.setObjectName('metricCard'); layout=QVBoxLayout(self); self.title=QLabel(title); self.title.setObjectName('muted'); self.value=QLabel('$0.00'); self.value.setObjectName('metricValue'); layout.addWidget(self.title); layout.addWidget(self.value)


class ReportingPage(QWidget):
    def __init__(self, service: ReportingService) -> None:
        super().__init__(); self.service=service; self.data:ReportData|None=None
        root=QVBoxLayout(self); root.setContentsMargins(18,18,18,18); root.setSpacing(12)
        top=QHBoxLayout(); title=QLabel('Reporting'); title.setObjectName('pageTitle'); top.addWidget(title); top.addStretch()
        self.range=QComboBox(); self.range.addItems(['This Month','Last Month','This Year','Last 12 Months','Custom']); self.range.currentTextChanged.connect(self._apply_range)
        self.from_date=QDateEdit(); self.from_date.setCalendarPopup(True); self.to_date=QDateEdit(); self.to_date.setCalendarPopup(True); self.from_date.setDate(date.today().replace(day=1)); self.to_date.setDate(date.today())
        refresh=QPushButton('Refresh'); refresh.clicked.connect(self.refresh); csv_btn=QPushButton('Export CSV'); csv_btn.clicked.connect(self._csv); xlsx_btn=QPushButton('Export Excel'); xlsx_btn.clicked.connect(self._xlsx); pdf_btn=QPushButton('Export PDF'); pdf_btn.clicked.connect(self._pdf)
        for w in (self.range,self.from_date,self.to_date,refresh,csv_btn,xlsx_btn,pdf_btn): top.addWidget(w)
        root.addLayout(top)
        metrics=QGridLayout(); self.cards={}
        labels=[('revenue','Revenue'),('profit','Profit'),('ppm','Profit per mile'),('fuel','Fuel'),('expenses','Expenses'),('miles','Miles'),('jobs','Jobs')]
        for i,(key,label) in enumerate(labels): c=MetricCard(label); self.cards[key]=c; metrics.addWidget(c,i//4,i%4)
        root.addLayout(metrics)
        self.tabs=QTabWidget(); root.addWidget(self.tabs,1)
        overview=QWidget(); ol=QVBoxLayout(overview); chart_row=QHBoxLayout(); self.revenue_chart=LineChart(); self.profit_chart=LineChart(); chart_row.addWidget(self._chart_box('Monthly Revenue',self.revenue_chart)); chart_row.addWidget(self._chart_box('Monthly Profit',self.profit_chart)); ol.addLayout(chart_row); self.monthly=self._table(['Month','Revenue','Profit','Fuel','Expenses','Miles','Jobs']); ol.addWidget(self.monthly); self.tabs.addTab(overview,'Monthly')
        self.yearly=self._table(['Year','Revenue','Profit','Fuel','Expenses','Miles','Jobs']); self.tabs.addTab(self._wrapped(self.yearly),'Yearly')
        self.customers=self._table(['Customer','Revenue','Cost','Profit','Miles','Profit / Mile','Jobs']); self.tabs.addTab(self._wrapped(self.customers),'By Customer')
        self.drivers=self._table(['Driver','Revenue','Cost','Profit','Miles','Profit / Mile','Jobs']); self.tabs.addTab(self._wrapped(self.drivers),'By Driver')
        self.expenses=self._table(['Expense Category','Amount']); self.tabs.addTab(self._wrapped(self.expenses),'Expenses')
        self._apply_range('This Month')

    def _chart_box(self,title:str,chart:QWidget)->QFrame:
        box=QFrame(); box.setObjectName('panel'); l=QVBoxLayout(box); h=QLabel(title); h.setObjectName('sectionTitle'); l.addWidget(h); l.addWidget(chart); return box
    def _wrapped(self,w:QWidget)->QWidget:
        box=QWidget(); l=QVBoxLayout(box); l.addWidget(w); return box
    def _table(self,headers:list[str])->QTableWidget:
        t=QTableWidget(0,len(headers)); t.setHorizontalHeaderLabels(headers); t.setSortingEnabled(True); t.setAlternatingRowColors(True); t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); t.horizontalHeader().setStretchLastSection(True); return t
    def _apply_range(self,text:str)->None:
        today=date.today()
        if text=='This Month': start=today.replace(day=1); end=today
        elif text=='Last Month':
            first=today.replace(day=1); end=first.fromordinal(first.toordinal()-1); start=end.replace(day=1)
        elif text=='This Year': start=date(today.year,1,1); end=today
        elif text=='Last 12 Months':
            try: start=today.replace(year=today.year-1)
            except ValueError: start=today.replace(year=today.year-1,day=28)
            end=today
        else: return
        self.from_date.setDate(start); self.to_date.setDate(end); self.refresh()
    def on_activated(self)->None: self.refresh()
    def refresh(self)->None:
        try: self.data=self.service.load(self.from_date.date().toPython(),self.to_date.date().toPython())
        except Exception as exc: QMessageBox.warning(self,'Reporting',str(exc)); return
        s=self.data.summary; vals={'revenue':money(s.revenue_cents),'profit':money(s.profit_cents),'ppm':money(s.profit_per_mile_cents),'fuel':money(s.fuel_cents),'expenses':money(s.expenses_cents),'miles':f'{s.miles:,.1f}','jobs':f'{s.jobs:,}'}
        for k,v in vals.items(): self.cards[k].value.setText(v)
        self.revenue_chart.set_data(self.data.trend,'revenue'); self.profit_chart.set_data(self.data.trend,'profit')
        self._fill(self.monthly,[[r.period,money(r.revenue_cents),money(r.profit_cents),money(r.fuel_cents),money(r.expenses_cents),f'{r.miles:,.1f}',str(r.jobs)] for r in self.data.trend])
        self._fill(self.yearly,[[r.period,money(r.revenue_cents),money(r.profit_cents),money(r.fuel_cents),money(r.expenses_cents),f'{r.miles:,.1f}',str(r.jobs)] for r in self.data.yearly])
        self._fill(self.customers,[[r.name,money(r.revenue_cents),money(r.cost_cents),money(r.profit_cents),f'{r.miles:,.1f}',money(r.profit_per_mile_cents),str(r.jobs)] for r in self.data.customers])
        self._fill(self.drivers,[[r.name,money(r.revenue_cents),money(r.cost_cents),money(r.profit_cents),f'{r.miles:,.1f}',money(r.profit_per_mile_cents),str(r.jobs)] for r in self.data.drivers])
        self._fill(self.expenses,[[r.category,money(r.amount_cents)] for r in self.data.expenses])
    def _fill(self,table:QTableWidget,rows:list[list[str]])->None:
        table.setSortingEnabled(False); table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate(row): table.setItem(i,j,QTableWidgetItem(value))
        table.resizeColumnsToContents(); table.setSortingEnabled(True)
    def _choose(self,suffix:str,label:str)->Path|None:
        name=f'McMahon-Report-{self.from_date.date().toString("yyyy-MM-dd")}-{self.to_date.date().toString("yyyy-MM-dd")}.{suffix}'
        path,_=QFileDialog.getSaveFileName(self,label,name,f'{label} (*.{suffix})'); return Path(path) if path else None
    def _csv(self)->None:
        if not self.data: self.refresh()
        path=self._choose('csv','CSV file');
        if path and self.data: self.service.export_csv(self.data,path); QMessageBox.information(self,'Reporting',f'CSV report saved to:\n{path}')
    def _xlsx(self)->None:
        if not self.data: self.refresh()
        path=self._choose('xlsx','Excel workbook');
        if path and self.data:
            try: self.service.export_excel(self.data,path); QMessageBox.information(self,'Reporting',f'Excel report saved to:\n{path}')
            except Exception as exc: QMessageBox.warning(self,'Reporting',str(exc))
    def _pdf(self)->None:
        if not self.data: self.refresh()
        path=self._choose('pdf','PDF document');
        if path and self.data: self.service.export_pdf(self.data,path); QMessageBox.information(self,'Reporting',f'PDF report saved to:\n{path}')
