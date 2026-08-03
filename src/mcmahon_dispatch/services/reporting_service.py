from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session, sessionmaker

from mcmahon_dispatch.repositories.reporting_repository import (
    ExpenseRow,
    RankedRow,
    ReportingRepository,
    SummaryTotals,
    TrendRow,
)


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


@dataclass(frozen=True, slots=True)
class ReportData:
    date_from: date
    date_to: date
    summary: SummaryTotals
    trend: list[TrendRow]
    yearly: list[TrendRow]
    customers: list[RankedRow]
    drivers: list[RankedRow]
    expenses: list[ExpenseRow]


class ReportingService:
    def __init__(self, factory: sessionmaker[Session], organization_id: str, documents_dir: Path) -> None:
        self.factory = factory
        self.organization_id = organization_id
        self.documents_dir = documents_dir

    def load(self, date_from: date, date_to: date) -> ReportData:
        if date_to < date_from:
            raise ValueError("The ending date cannot be before the starting date.")
        with self.factory() as session:
            repo = ReportingRepository(session, self.organization_id)
            return ReportData(date_from, date_to, repo.summary(date_from, date_to), repo.monthly_trend(date_from, date_to), repo.yearly_trend(date_from, date_to), repo.by_customer(date_from, date_to), repo.by_driver(date_from, date_to), repo.expense_breakdown(date_from, date_to))

    def export_csv(self, data: ReportData, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.writer(handle)
            writer.writerow(["McMahon Dispatch Reporting"])
            writer.writerow(["Period", data.date_from.isoformat(), data.date_to.isoformat()])
            writer.writerow([])
            writer.writerow(["Metric", "Value"])
            s=data.summary
            for name,value in [("Revenue",money(s.revenue_cents)),("Profit",money(s.profit_cents)),("Miles",f"{s.miles:,.1f}"),("Profit per mile",money(s.profit_per_mile_cents)),("Fuel",money(s.fuel_cents)),("Expenses",money(s.expenses_cents)),("Jobs",s.jobs)]: writer.writerow([name,value])
            writer.writerow([]); writer.writerow(["Monthly", "Revenue", "Profit", "Fuel", "Expenses", "Miles", "Jobs"])
            for row in data.trend: writer.writerow([row.period, money(row.revenue_cents), money(row.profit_cents), money(row.fuel_cents), money(row.expenses_cents), f"{row.miles:.1f}", row.jobs])
            writer.writerow([]); writer.writerow(["Year", "Revenue", "Profit", "Fuel", "Expenses", "Miles", "Jobs"])
            for row in data.yearly: writer.writerow([row.period, money(row.revenue_cents), money(row.profit_cents), money(row.fuel_cents), money(row.expenses_cents), f"{row.miles:.1f}", row.jobs])
            writer.writerow([]); writer.writerow(["Customer", "Revenue", "Cost", "Profit", "Miles", "Profit per mile", "Jobs"])
            for row in data.customers: writer.writerow([row.name,money(row.revenue_cents),money(row.cost_cents),money(row.profit_cents),f"{row.miles:.1f}",money(row.profit_per_mile_cents),row.jobs])
            writer.writerow([]); writer.writerow(["Driver", "Revenue", "Cost", "Profit", "Miles", "Profit per mile", "Jobs"])
            for row in data.drivers: writer.writerow([row.name,money(row.revenue_cents),money(row.cost_cents),money(row.profit_cents),f"{row.miles:.1f}",money(row.profit_per_mile_cents),row.jobs])
        return path

    def export_excel(self, data: ReportData, path: Path) -> Path:
        import xlsxwriter
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook=xlsxwriter.Workbook(path)
        header=workbook.add_format({'bold':True,'bg_color':'#111827','font_color':'#FFFFFF','border':1})
        money_fmt=workbook.add_format({'num_format':'$#,##0.00','border':1})
        number=workbook.add_format({'num_format':'#,##0.0','border':1})
        cell=workbook.add_format({'border':1})
        title=workbook.add_format({'bold':True,'font_size':18,'font_color':'#F97316'})
        summary=workbook.add_worksheet('Summary'); summary.write('A1','McMahon Dispatch Report',title); summary.write('A2',f'{data.date_from:%b %d, %Y} - {data.date_to:%b %d, %Y}')
        metrics=[('Revenue',data.summary.revenue_cents/100),('Profit',data.summary.profit_cents/100),('Profit per mile',data.summary.profit_per_mile_cents/100),('Fuel',data.summary.fuel_cents/100),('Expenses',data.summary.expenses_cents/100),('Miles',data.summary.miles),('Jobs',data.summary.jobs)]
        summary.write_row(3,0,['Metric','Value'],header)
        for r,(name,value) in enumerate(metrics,4): summary.write(r,0,name,cell); summary.write(r,1,value,money_fmt if name not in {'Miles','Jobs'} else number)
        summary.set_column('A:A',24); summary.set_column('B:B',18)
        def add_ranked(name:str, rows:list[RankedRow]):
            ws=workbook.add_worksheet(name); cols=['Name','Revenue','Cost','Profit','Miles','Profit per mile','Jobs']; ws.write_row(0,0,cols,header)
            for r,row in enumerate(rows,1):
                ws.write(r,0,row.name,cell); ws.write(r,1,row.revenue_cents/100,money_fmt); ws.write(r,2,row.cost_cents/100,money_fmt); ws.write(r,3,row.profit_cents/100,money_fmt); ws.write(r,4,row.miles,number); ws.write(r,5,row.profit_per_mile_cents/100,money_fmt); ws.write(r,6,row.jobs,cell)
            ws.set_column('A:A',30); ws.set_column('B:G',16); ws.autofilter(0,0,max(1,len(rows)),len(cols)-1); ws.freeze_panes(1,0)
        add_ranked('Customers',data.customers); add_ranked('Drivers',data.drivers)
        ws=workbook.add_worksheet('Monthly'); cols=['Month','Revenue','Profit','Fuel','Expenses','Miles','Jobs']; ws.write_row(0,0,cols,header)
        for r,row in enumerate(data.trend,1):
            ws.write(r,0,row.period,cell); ws.write(r,1,row.revenue_cents/100,money_fmt); ws.write(r,2,row.profit_cents/100,money_fmt); ws.write(r,3,row.fuel_cents/100,money_fmt); ws.write(r,4,row.expenses_cents/100,money_fmt); ws.write(r,5,row.miles,number); ws.write(r,6,row.jobs,cell)
        ws.set_column('A:A',14); ws.set_column('B:G',16); ws.freeze_panes(1,0)
        ys=workbook.add_worksheet('Yearly'); ys.write_row(0,0,cols,header)
        for r,row in enumerate(data.yearly,1):
            ys.write(r,0,row.period,cell); ys.write(r,1,row.revenue_cents/100,money_fmt); ys.write(r,2,row.profit_cents/100,money_fmt); ys.write(r,3,row.fuel_cents/100,money_fmt); ys.write(r,4,row.expenses_cents/100,money_fmt); ys.write(r,5,row.miles,number); ys.write(r,6,row.jobs,cell)
        ys.set_column('A:A',14); ys.set_column('B:G',16); ys.freeze_panes(1,0)
        workbook.close(); return path

    def export_pdf(self, data: ReportData, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        styles=getSampleStyleSheet(); doc=SimpleDocTemplate(str(path),pagesize=landscape(letter),leftMargin=.45*inch,rightMargin=.45*inch,topMargin=.45*inch,bottomMargin=.45*inch,title='McMahon Dispatch Report')
        story=[Paragraph('McMahon Dispatch Report',styles['Title']),Paragraph(f'{data.date_from:%b %d, %Y} - {data.date_to:%b %d, %Y}',styles['Heading2']),Spacer(1,10)]
        s=data.summary
        summary_rows=[['Revenue','Profit','Profit / Mile','Fuel','Expenses','Miles','Jobs'],[money(s.revenue_cents),money(s.profit_cents),money(s.profit_per_mile_cents),money(s.fuel_cents),money(s.expenses_cents),f'{s.miles:,.1f}',str(s.jobs)]]
        t=Table(summary_rows,colWidths=[1.35*inch]*7); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#111827')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.5,colors.HexColor('#CBD5E1')),('ALIGN',(0,0),(-1,-1),'CENTER'),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)])); story += [t,Spacer(1,14)]
        def ranked(title:str, rows:list[RankedRow]):
            story.append(Paragraph(title,styles['Heading2']))
            table_rows=[['Name','Revenue','Cost','Profit','Miles','Profit / Mile','Jobs']]+[[r.name,money(r.revenue_cents),money(r.cost_cents),money(r.profit_cents),f'{r.miles:,.1f}',money(r.profit_per_mile_cents),str(r.jobs)] for r in rows[:25]]
            tab=Table(table_rows,colWidths=[2.6*inch,1.1*inch,1.1*inch,1.1*inch,.8*inch,1.1*inch,.55*inch],repeatRows=1); tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#111827')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#CBD5E1')),('FONTSIZE',(0,0),(-1,-1),8),('ALIGN',(1,1),(-1,-1),'RIGHT'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F8FAFC')])]))
            story.extend([tab,Spacer(1,12)])
        ranked('Profit by Customer',data.customers); ranked('Profit by Driver',data.drivers)
        doc.build(story); return path
