from PyQt6.QtGui import QTextDocument, QPageSize
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
from PyQt6.QtCore import QSizeF
from PyQt6.QtWidgets import QMessageBox
from datetime import datetime

def print_receipt(parent_widget, order_data, payments_list):
    """
    Generate an HTML receipt and print it to the Xprinter thermal printer.
    """
    items_list = order_data.get('items', [])
    total_amount = order_data.get('total_amount', 0.0)
    order_type = order_data.get('order_type', '')
    ticket_number = order_data.get('ticket_number', '')
    comment = order_data.get('comment', '')

    total_paid = sum(p['amount'] for p in payments_list)
    change = max(0, total_paid - total_amount)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Professional Thermal Receipt HTML
    html = f"""
    <html>
    <head>
    <style>
        @page {{ margin: 0; }}
        body {{ 
            font-family: 'Courier New', monospace; 
            font-size: 10px; 
            width: 280px; /* Standard for 80mm printers in pixels */
            margin: 0; padding: 5px; 
        }}
        .center {{ text-align: center; }}
        .right {{ text-align: right; }}
        .bold {{ font-weight: bold; }}
        .ticket {{ font-size: 20px; font-weight: bold; text-align: center; margin: 5px 0; border: 1px solid #000; padding: 3px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 5px; }}
        th, td {{ border-bottom: 1px dashed #000; padding: 2px 0; }}
        .total-box {{ border-top: 1px solid #000; margin-top: 5px; padding-top: 5px; }}
    </style>
    </head>
    <body>
        <div class="center bold" style="font-size: 14px;">JAZIRA POS</div>
        <div class="center">Xarid cheki</div>
        <div class="center">{date_str}</div>
        <div class="center bold">Tur: {order_type}</div>
    """

    if ticket_number:
        html += f'<div class="ticket">STIKER: {ticket_number}</div>'

    html += """
        <table>
            <tr>
                <th style="width:60%">Nomi</th>
                <th style="width:10%">S</th>
                <th class="right" style="width:30%">Summa</th>
            </tr>
    """

    for item in items_list:
        html += f"""
            <tr>
                <td>{item['name']}</td>
                <td>{int(item['qty'])}</td>
                <td class="right">{(item['qty'] * item['price']):,.0f}</td>
            </tr>
        """

    html += f"""
        </table>
        
        <div class="total-box">
            <div style="width: 100%; overflow: hidden; font-size: 12px;" class="bold">
                <span style="float: left;">JAMI:</span>
                <span style="float: right;">{total_amount:,.0f} UZS</span>
            </div>
        </div>

        <div style="margin-top: 5px;">
            <div class="bold" style="font-size: 9px; margin-bottom: 2px;">TO'LOVLAR:</div>
    """

    for p in payments_list:
        if p['amount'] > 0:
            html += f"""
            <div style="width: 100%; overflow: hidden;">
                <span style="float: left;">{p['mode_of_payment']}:</span>
                <span style="float: right;">{p['amount']:,.0f}</span>
            </div>
            """

    if change > 0:
        html += f"""
        <div style="width: 100%; overflow: hidden; margin-top: 3px; border-top: 0.5px solid #000;">
            <span style="float: left; font-weight: bold;">QAYTIM:</span>
            <span style="float: right; font-weight: bold;">{change:,.0f} UZS</span>
        </div>
        """

    if comment:
        html += f'<div style="margin-top: 5px; font-size: 9px;"><strong>Izoh:</strong> {comment}</div>'

    html += """
        <div class="center" style="margin-top: 15px;">Xaridingiz uchun rahmat!</div>
        <div class="center">.</div><div class="center">.</div>
    </body>
    </html>
    """

    document = QTextDocument()
    document.setHtml(html)
    document.setDocumentMargin(0)

    # Initialize Printer
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(QPageSize(QSizeF(80, 297), QPageSize.Unit.Millimeter))
    printer.setFullPage(True)
    
    # Try to print to default printer without dialog
    # If the printer is not default, we show the dialog once
    if not printer.printerName():
        dialog = QPrintDialog(printer, parent_widget)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return False

    document.print(printer)
    return True
