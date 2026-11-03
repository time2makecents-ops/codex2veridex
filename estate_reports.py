"""Local estate-sale documents. Returned bytes must go through the artifact store."""
import csv
import io
import json
from decimal import Decimal
from xml.sax.saxutils import escape


KINDS={'proposal','inventory','labels','operations','marketing','settlement','closeout','receipt','calendar'}


def rows_for(snapshot,kind):
    sale=snapshot['project']
    if kind=='inventory' or kind=='labels':
        return [{key:row.get(key,'') for key in ('id','title','location','lot','condition','quantity','available','reserved','sold','disposed','approved_price_cents')} for row in snapshot['inventory']]
    if kind=='settlement':return [{'field':key.removesuffix('_cents').replace('_',' '),'value':f"{sale['currency']} {Decimal(value)/100:.2f}" if value is not None else 'Not configured'} for key,value in snapshot['finance'].items()]
    if kind=='proposal':return [{'field':key,'value':sale.get(key,'')} for key in ('client_name','address','scope','exclusions','sale_date','end_date','commission_percent','fixed_fee','cleanup_requested','removal_requested','cleanup_instructions','agreement_notes')]
    if kind=='marketing':return [{'field':key,'value':sale.get(key,'')} for key in ('public_description','sale_date','end_date')]
    records=snapshot['records']
    if kind=='receipt':
        records=[row for row in records if row['kind']=='entry' and row['type'] in {'sale','return'}]
        titles={item['id']:item['title'] for item in snapshot['inventory']}
        return [{'receipt':row['id'][-8:].upper(),'type':row['type'],'date':row['date'],'item':titles.get(row['item_id'],'Item'),'quantity':row['quantity'],'amount':f"{sale['currency']} {Decimal(row['amount_cents'])/100:.2f}",'tax':f"{sale['currency']} {Decimal(row.get('tax_cents',0))/100:.2f}",'total':f"{sale['currency']} {Decimal(row['amount_cents']+row.get('tax_cents',0))/100:.2f}",'method':row['payment_method']} for row in records]
    if kind=='closeout':records=[row for row in records if row['kind']=='entry' and row['type'] in {'disposition','payout','expense'}]
    return [{key:value for key,value in row.items() if key not in {'version'}} for row in records if kind!='operations' or row['kind'] in {'task','document'}]


def calendar(snapshot):
    def safe(value):return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Veridex//Estate Sales//EN','CALSCALE:GREGORIAN']
    events=[(row['id'],row['title'],row['due']) for row in snapshot['records'] if row['kind']=='task' and row.get('due')]
    sale=snapshot['project']
    if sale.get('sale_date'):events.append((sale['id'],sale['name'],sale['sale_date']))
    for identifier,title,due in events:
        lines+=['BEGIN:VEVENT','UID:'+safe(identifier)+'@veridex','DTSTAMP:'+sale['updated_at'][:19].replace('-','').replace(':','')+'Z','DTSTART;VALUE=DATE:'+due.replace('-',''),'SUMMARY:'+safe(title),'END:VEVENT']
    lines+=['END:VCALENDAR']
    # Fold at UTF-8 boundaries; escape user newlines before adding any properties.
    folded=[]
    for line in lines:
        current=''
        for char in line:
            if len((current+char).encode())>73:folded.append(current);current=' '
            current+=char
        folded.append(current)
    return ('\r\n'.join(folded)+'\r\n').encode()


def render(snapshot,kind,format='pdf'):
    if kind not in KINDS:raise ValueError('Unsupported report')
    if kind=='calendar':return calendar(snapshot),'.ics','text/calendar'
    if format not in {'pdf','csv','xlsx','docx'}:raise ValueError('Unsupported report format')
    rows=rows_for(snapshot,kind)
    headers=list(dict.fromkeys(key for row in rows for key in row)) or ['Record']
    values=[[str(row.get(key,'')) for key in headers] for row in rows]
    title=snapshot['project']['name']+' - '+kind.title()
    output=io.BytesIO()
    if format=='csv':
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers)
        # Protect spreadsheet exports against formula interpretation.
        writer.writerows([["'"+v if v.startswith(('=','+','-','@','\t','\r')) else v for v in row] for row in values])
        return stream.getvalue().encode('utf-8-sig'),'.csv','text/csv'
    if format=='xlsx':
        from openpyxl import Workbook
        book=Workbook();sheet=book.active;sheet.title=kind[:31];sheet.append(headers)
        for row in values:
            sheet.append(row)
            for cell in sheet[sheet.max_row]:cell.data_type='s'
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions;book.save(output)
        return output.getvalue(),'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    if format=='docx':
        from docx import Document
        doc=Document();doc.add_heading(title,0)
        if kind=='proposal':doc.add_paragraph('Draft for review. Signed approval is recorded separately.')
        for row in rows:
            for key,value in row.items():doc.add_paragraph(f'{key}: {value}')
            doc.add_paragraph('')
        doc.save(output)
        return output.getvalue(),'.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,KeepTogether,Image
    from reportlab.lib.styles import getSampleStyleSheet
    styles=getSampleStyleSheet();story=[Paragraph(escape(title),styles['Title'])]
    if kind=='proposal':story.append(Paragraph('Draft for review. Signed approval is recorded separately.',styles['Normal']))
    for row in rows:
        block=[]
        if kind=='labels':
            import qrcode
            image=io.BytesIO();qrcode.make(row['id']).save(image,format='PNG');image.seek(0)
            price=row.get('approved_price_cents')
            label=f"{row['title']} - {snapshot['project'].get('currency','USD')} {price/100:.2f}" if price is not None else f"{row['title']} - Price pending"
            block=[Paragraph(escape(label),styles['Heading2']),Paragraph(escape(row['id']),styles['Normal']),Image(image,60,60)]
        else:
            block=[Paragraph(escape(str(key))+': '+escape(str(value)).replace('\n','<br/>'),styles['Normal']) for key,value in row.items()]
        story+=([KeepTogether(block)] if kind=='labels' else block)+[Spacer(1,12)]
    SimpleDocTemplate(output).build(story)
    return output.getvalue(),'.pdf','application/pdf'
