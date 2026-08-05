{
    'name': 'POS Custom Report',
    'version': '17.0.1.1.0',
    'category': 'Point of Sale',
    'summary': 'Personalizacion del reporte de cierre de sesion POS + Validación Stock + Filtro por Proveedor',
    'depends': ['point_of_sale'],
    'data': [
        'security/pos_excel_report_wizard_security.xml',
        'views/report_action.xml',
        'reports/pos_session_report_templates.xml',
        'views/pos_session_views.xml',
        'wizards/pos_sale_details_wizard_views.xml',
        'wizards/pos_excel_report_wizard_views.xml',
    ],

    'assets': {
        'point_of_sale._assets_pos': [
            'pos_custom_report/static/src/js/pos_stock_validation.js',
        ],
    },
    
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}