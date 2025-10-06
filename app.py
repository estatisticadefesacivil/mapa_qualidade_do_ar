from flask import Flask, render_template, request, send_file, jsonify
import pandas as pd
import io
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, Frame, PageBreak
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader


app = Flask(__name__)

# Link da planilha do Google Sheets em formato XLSX
EXCEL_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vTNr4SxZ7Uz0AKt4v3X9s897idlry11JpClfyfzh9vOiCZgK5U7r1JEV5KDDiqaX0P-u63hxQG_CSEj/pub?output=xlsx'


@app.route('/')
def index():
    try:
        df = pd.read_excel(EXCEL_URL)
        municipios = sorted(df['MUNICÍPIO'].dropna().unique())
        mapa_dados = [
            {
                'cidade': row.get('MUNICÍPIO'),
                'lat': row.get('latitude'),
                'lon': row.get('longitude'),
                'qualidade': row.get('Valor'),
                'sensor': row.get('name'),
                'parametro': row.get('pm2.5_24hour')
            }
            for _, row in df.iterrows()
            if pd.notnull(row.get('latitude')) and pd.notnull(row.get('longitude'))
        ]
    except Exception as e:
        print("Erro ao carregar dados:", e)
        municipios = []
        mapa_dados = [] 

    return render_template('index.html', municipios=municipios, mapa_dados=mapa_dados)

@app.route('/dados_mapa', methods=['GET'])
def dados_mapa():
    municipio = request.args.get('municipio')
    classificacao = request.args.get('classificacao')

    try:
        df = pd.read_excel(EXCEL_URL)
    except Exception as e:
        return jsonify([])

    if municipio:
        df = df[df['MUNICÍPIO'].str.lower() == municipio.lower()]
    if classificacao:
        df = df[df['Valor'].str.lower() == classificacao.lower()]

    mapa_dados = []
    for _, row in df.iterrows():
        if pd.notnull(row.get('latitude')) and pd.notnull(row.get('longitude')):
            mapa_dados.append({
                'cidade': row.get('MUNICÍPIO'),
                'lat': row.get('latitude'),
                'lon': row.get('longitude'),
                'qualidade': row.get('Valor'),
                'sensor': row.get('name'),
                'parametro': row.get('pm2.5_24hour')
            })

    return jsonify(mapa_dados)

def _classificar_faixa_pm25(valor):
    try:
        v = float(valor)
    except Exception:
        return "-"
    if v <= 25:
        return "Boa"
    if v <= 50:
        return "Moderada"
    if v <= 75:
        return "Ruim"
    if v <= 125:
        return "Muito Ruim"
    return "Péssima"

@app.route('/dados_agregado', methods=['GET'])
def dados_agregado():
    """
    Agrega por município calculando a média de pm2.5_24hour e a quantidade de sensores.
    Filtros opcionais: municipio (string), classificacao (pela faixa resultante após média).
    """
    municipio = request.args.get('municipio')
    classificacao = request.args.get('classificacao')

    try:
        df = pd.read_excel(EXCEL_URL)
    except Exception:
        return jsonify([])

    # Normaliza colunas esperadas
    if 'MUNICÍPIO' not in df.columns or 'pm2.5_24hour' not in df.columns:
        return jsonify([])

    # Aplica filtro por município nas observações individuais (antes da agregação)
    if municipio:
        df = df[df['MUNICÍPIO'].astype(str).str.lower() == str(municipio).lower()]

    # Remove linhas sem valor métrico ou município
    df = df[pd.notnull(df['MUNICÍPIO']) & pd.notnull(df['pm2.5_24hour'])]

    if df.empty:
        return jsonify([])

    # Agrega
    agrupado = (
        df.groupby('MUNICÍPIO', as_index=False)
          .agg(pm25_media=('pm2.5_24hour', 'mean'), sensores=('pm2.5_24hour', 'count'))
    )

    # Classifica pela média
    agrupado['faixa'] = agrupado['pm25_media'].apply(_classificar_faixa_pm25)

    # Opcional: filtrar por classificação da faixa final
    if classificacao:
        agrupado = agrupado[agrupado['faixa'].str.lower() == classificacao.lower()]

    # Formata saída
    resultado = [
        {
            'municipio': row['MUNICÍPIO'],
            'pm25_media': float(row['pm25_media']),
            'sensores': int(row['sensores']),
            'faixa': row['faixa']
        }
        for _, row in agrupado.iterrows()
    ]

    return jsonify(resultado)

@app.route('/poligonos_municipios', methods=['GET'])
def poligonos_municipios():
    """
    Retorna dados agregados por município com informações para colorir polígonos.
    """
    try:
        df = pd.read_excel(EXCEL_URL)
    except Exception:
        return jsonify([])

    # Normaliza colunas esperadas
    if 'MUNICÍPIO' not in df.columns or 'pm2.5_24hour' not in df.columns:
        return jsonify([])

    # Remove linhas sem valor métrico ou município
    df = df[pd.notnull(df['MUNICÍPIO']) & pd.notnull(df['pm2.5_24hour'])]

    if df.empty:
        return jsonify([])

    # Agrega por município
    agrupado = (
        df.groupby('MUNICÍPIO', as_index=False)
          .agg(pm25_media=('pm2.5_24hour', 'mean'), sensores=('pm2.5_24hour', 'count'))
    )

    # Classifica pela média
    agrupado['faixa'] = agrupado['pm25_media'].apply(_classificar_faixa_pm25)

    # Mapeamento de cores para cada faixa
    cores_por_faixa = {
        'Boa': '#009966',
        'Moderada': '#DDCA00', 
        'Ruim': '#F5BA09',
        'Muito Ruim': '#EE3608',
        'Péssima': '#660099'
    }

    # Formata saída com cores
    resultado = [
        {
            'municipio': row['MUNICÍPIO'],
            'pm25_media': float(row['pm25_media']),
            'sensores': int(row['sensores']),
            'faixa': row['faixa'],
            'cor': cores_por_faixa.get(row['faixa'], '#CCCCCC')
        }
        for _, row in agrupado.iterrows()
    ]

    return jsonify(resultado)

@app.route('/exportar', methods=['POST'])
def exportar():
    municipio = request.form.get('municipio')
    valor_classificacao = request.form.get('valor')

    try:
        df = pd.read_excel(EXCEL_URL)
    except Exception as e:
        return f"Erro ao carregar o arquivo: {str(e)}", 500

    if municipio:
        df = df[df['MUNICÍPIO'].str.lower() == municipio.lower()]
    if valor_classificacao:
        df = df[df['Valor'].str.lower() == valor_classificacao.lower()]

    if df.empty:
        return f"Nenhum dado encontrado para os filtros fornecidos.", 404
    
    # Calcular estatísticas
    total_sensores = len(df)
    qualidade_geral = df['Valor'].mode().iloc[0] if not df['Valor'].empty else "---"

    # Mapa de cores para o NOME do sensor conforme a qualidade
    sensor_color_by_quality = {
        'boa': '#0F9D58',          # verde
        'moderada': '#DDCA00',     # amarelo/âmbar escuro
        'muito ruim': '#C62828',   # vermelho
        'ruim': '#F5BA09',         # laranja
        'péssima': '#6A1B9A',      # roxo
    }

    frases = []
    for _, row in df.iterrows():
        valor_cls = str(row.get('Valor', '') or '').lower()
        sensor_name = row.get('name', 'Desconhecido')
        sensor_color = sensor_color_by_quality.get(valor_cls, '#767575')
        sensor_name_colored = f"<font color='{sensor_color}'><b>{sensor_name}</b></font>"
        # Se filtrou apenas por classificação (sem município específico)
        if municipio and valor_classificacao:
            frase = (
                f"<b>SENSOR:</b> {sensor_name_colored}<br/>"
                f"<b>LOCALIZAÇÃO:</b> {row.get('latitude', 'N/A')}, {row.get('longitude', 'N/A')}<br/>"
                f"<b>REGISTRO:</b> Índice de qualidade do ar de {row.get('pm2.5_24hour', 'N/A')} ug/m³, "
                f"classificada como <b>{row.get('Valor', 'N/A')}</b> nas últimas 24 horas."
        )
        elif not municipio or valor_classificacao:
            frase = (
                f"<b>SENSOR:</b> {sensor_name_colored}<br/>"
                f"<b>MUNICÍPIO:</b> {row.get('MUNICÍPIO', 'N/A')}<br/>"
                f"<b>LOCALIZAÇÃO:</b> {row.get('latitude', 'N/A')}, {row.get('longitude', 'N/A')}<br/>"
                f"<b>REGISTRO:</b> Índice de qualidade do ar de {row.get('pm2.5_24hour', 'N/A')} ug/m³, "
                f"classificada como <b>{row.get('Valor', 'N/A')}</b> nas últimas 24 horas."
        )
        # Se filtrou por município (com ou sem classificação)
        else:
            frase = (
                f"<b>SENSOR:</b> {sensor_name_colored}<br/>"
                f"<b>LOCALIZAÇÃO:</b> {row.get('latitude', 'N/A')}, {row.get('longitude', 'N/A')}<br/>"
                f"<b>REGISTRO:</b> Índice de qualidade do ar de {row.get('pm2.5_24hour', 'N/A')} ug/m³, "
                f"classificada como <b>{row.get('Valor', 'N/A')}</b> nas últimas 24 horas."
        )
        frases.append(frase)

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=-7, bottomMargin=0)
    styles = getSampleStyleSheet()
    story = []

    # Imagem do topo será adicionada pela função add_header() em todas as páginas

    # Título do relatório com ícone
    # Baixar ícone do GitHub
    try:
        icon_resp = requests.get('https://github.com/estatisticadefesacivil/mapa_qualidade_do_ar/blob/main/icone_relatorio.png?raw=true')
        if icon_resp.status_code == 200:
            icon_bytes = io.BytesIO(icon_resp.content)
            icon_img = Image(icon_bytes, width=35, height=35)
        else:
            icon_img = None
    except:
        icon_img = None

    # Estilos customizados
    styles_custom = getSampleStyleSheet()
    styles_custom.add(ParagraphStyle(name='TituloLinha1', fontName='Helvetica', fontSize=12, leading=20, spaceAfter=0))
    styles_custom.add(ParagraphStyle(name='TituloLinha2', fontName='Helvetica-Bold', fontSize=15, leading=25, spaceAfter=15))
    
    # Estilos para cada classificação de qualidade do ar
    styles_custom.add(ParagraphStyle(name='Boa', fontName='Helvetica', fontSize=7.5, leading=19, 
                                    backColor=colors.HexColor('#F2FAF7'), 
                                    leftIndent=0, rightIndent=30, 
                                    spaceBefore=0, spaceAfter=0))
    styles_custom.add(ParagraphStyle(name='Moderada', fontName='Helvetica', fontSize=7.5, leading=19, 
                                    backColor=colors.HexColor('#FFFDED'), 
                                    leftIndent=0, rightIndent=30, 
                                    spaceBefore=0, spaceAfter=0))
    styles_custom.add(ParagraphStyle(name='Ruim', fontName='Helvetica', fontSize=7.5, leading=19, 
                                    backColor=colors.HexColor('#FFF6DA'), 
                                    leftIndent=0, rightIndent=30, 
                                    spaceBefore=0, spaceAfter=0))
    styles_custom.add(ParagraphStyle(name='Muito Ruim', fontName='Helvetica', fontSize=7.5, leading=19, 
                                    backColor=colors.HexColor('#FFF2EF'), 
                                    leftIndent=0, rightIndent=30, 
                                    spaceBefore=0, spaceAfter=0))
    styles_custom.add(ParagraphStyle(name='Péssima', fontName='Helvetica', fontSize=7.5, leading=19, 
                                    backColor=colors.HexColor('#F7F2FA'), 
                                    leftIndent=0, rightIndent=30, 
                                    spaceBefore=0, spaceAfter=0))


    # Construir título com ícone ao lado de ambos os textos
    if icon_img:
        # Criar tabela com ícone + ambos os textos
        title_text = "RELATÓRIO DE<br/><font name='Helvetica-Bold' size='18'>Qualidade do ar</font>"
        title_table = Table([[icon_img, Paragraph(title_text, styles_custom['TituloLinha1'])]], 
                           colWidths=[40, 200])
        title_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 28),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('LEFTPADDING', (1,0), (1,0), 10),  # Padding à esquerda do texto
        ]))
    else:
        # Fallback sem ícone
        title_flow = []
        title_flow.append(Paragraph("RELATÓRIO DE", styles_custom['TituloLinha1']))
        title_flow.append(Paragraph("Qualidade do ar", styles_custom['TituloLinha2']))
        title_table = Table([[title_flow]], colWidths=[480])
        title_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

    # Criar legenda como imagem
    legenda_img = None
    try:
        legenda_resp = requests.get('https://github.com/estatisticadefesacivil/mapa_qualidade_do_ar/blob/main/legenda-relatorio.png?raw=true')
        if legenda_resp.status_code == 200:
            legenda_bytes = io.BytesIO(legenda_resp.content)
            legenda_img = Image(legenda_bytes, width=282, height=4)
    except:
        pass

    # Valores para a caixa de informações (definir antes de montar a tabela)
    if municipio and valor_classificacao:
        municipio_display = municipio.upper()
        qualidade_display = valor_classificacao.upper()
    elif municipio:
        municipio_display = municipio.upper()
        qualidade_display = "-"
    else:
        municipio_display = "TODOS"
        qualidade_display = valor_classificacao.upper() if valor_classificacao else "-"

    # Criar caixa de informações como tabela
    info_data = [
        ["Município:", municipio_display],
        ["Quantidade de Sensores:", str(total_sensores)],
        ["Qualidade do Ar:", qualidade_display]
    ]
    
    info_table = Table(info_data, colWidths=[70, 94])  # Ajustar largura das colunas para 180 - 8*2 = 164
    info_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -3), 'LEFT'),   # Rótulos (coluna 0) alinhados à esquerda
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),  # Valores (coluna 1) alinhados à direita
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'), # Rótulos normais
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'), # Apenas o valor do Município (célula 1,0) em negrito
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica'), # Outros valores (células 1,1 e 1,2) normais
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#333333')),
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#FFFFFF')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))

    # Montar coluna esquerda (título + legenda)
    left_content = [title_table]
    if legenda_img:
        left_content.append(Spacer(1, 8))
        left_content.append(legenda_img)
    
    left_table = Table([[left_content]], colWidths=[12*cm])
    left_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))

    # Header em duas colunas
    created_at = datetime.now().strftime('%d/%m/%Y às %H:%M:%S')
    # Estilo para o texto de criação (menor e alinhado à esquerda)
    created_style = ParagraphStyle(
        name='CreatedStyle',
        parent=styles['Normal'],
        fontSize=6,
        textColor=HexColor('#3C3C3C'),
        leftIndent=60 # Alinhar com o conteúdo da caixa
    )
    right_content = [Spacer(1, 10), info_table, Spacer(1, 19), Paragraph(f"| Criado em {created_at}", created_style)]
    header_table = Table([[left_table, right_content]], colWidths=[12*cm, 6*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),  # Alinhar caixa à direita
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))

    # Função para adicionar cabeçalho completo
    def add_header():
        # Adicionar imagem do topo em cada página
        try:
            top_image_response = requests.get('https://github.com/estatisticadefesacivil/mapa_qualidade_do_ar/blob/main/cima.png?raw=true')
            if top_image_response.status_code == 200:
                top_image_bytes = io.BytesIO(top_image_response.content)
                story.append(Image(top_image_bytes, width=600, height=5))
                story.append(Spacer(1, 20))
        except:
            pass
        
        story.append(header_table)
        story.append(Spacer(1, 20))

    # Adicionar cabeçalho na primeira página
    add_header()

    # Dividir sensores em páginas de 7
    sensores_por_pagina = 7
    total_sensores = len(frases)
    
    # Adicionar frases dos sensores com cores de fundo baseadas na classificação
    for i, frase in enumerate(frases):
        # Determinar o estilo baseado na classificação na frase
        upper_frase = frase.upper()
        if 'BOA' in upper_frase:
            style_name = 'Boa'
        elif 'MODERADA' in upper_frase:
            style_name = 'Moderada'
        elif 'MUITO RUIM' in upper_frase:
            style_name = 'Muito Ruim'
        elif 'RUIM' in upper_frase:
            style_name = 'Ruim'
        elif 'PÉSSIMA' in upper_frase:
            style_name = 'Péssima'
        else:
            style_name = 'Normal'  # Fallback para casos não identificados
        
        story.append(Paragraph(frase, styles_custom[style_name]))
        story.append(Spacer(1, 10))
        
        # Adicionar quebra de página a cada 7 sensores (exceto na última página)
        if (i + 1) % sensores_por_pagina == 0 and (i + 1) < total_sensores:
            story.append(PageBreak())
            # Adicionar cabeçalho em cada nova página
            add_header()

    # Criar tabela de informações
    info_data = [
        ["Município:", municipio_display],
        ["Quantidade de Sensores:", str(total_sensores)],
        ["Qualidade do Ar:", qualidade_display]
    ]
    
    info_table = Table(info_data, colWidths=[4.5*cm, 5*cm])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#333333')),
        ('BOX', (0, 0), (-1, -1), 1, HexColor('#CCCCCC')),
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#FFFFFF')),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))

    # URL da imagem de rodapé
    RODAPE_URL = 'https://github.com/estatisticadefesacivil/mapa_qualidade_do_ar/blob/main/rodape_relatorio.png?raw=true'

    # Callback para desenhar borda arredondada na caixa de info e rodapé
    def draw_rounded_border_and_footer(canvas, doc):
        # Imagem do rodapé ocupando da metade da página para baixo
        try:
            rodape_img = ImageReader(RODAPE_URL)
            img_w, img_h = rodape_img.getSize()
            page_w, page_h = A4
            half_h = page_h / 2.0

            # Ajuste mantendo proporção, preferindo preencher a altura da metade inferior
            target_h = half_h
            target_w = (img_w / img_h) * target_h
            if target_w > page_w:
                target_w = page_w
                target_h = (img_h / img_w) * target_w

            x = (page_w - target_w) / 2.0
            y = 0  # começa no rodapé

            canvas.drawImage(rodape_img, x, y, width=target_w, height=target_h, mask='auto')
        except Exception as e:
            print("Erro carregando/desenhando imagem de rodapé:", e)
        # Posição da caixa de info no header (aproximada)

        x = A4[0] - 210 # Posição X da caixa
        y = A4[1] - 28   # Posição Y da caixa
        width = 175     # Largura da caixa
        height = 57    # Altura da caixa
        
        # Desenhar borda arredondada
        canvas.setStrokeColor(HexColor('#D8D8D8'))
        canvas.setLineWidth(0.4)
        canvas.roundRect(x, y - height, width, height, 4, fill=0, stroke=1)
        
        # Adicionar rodapé com contagem de sensores
        canvas.saveState()
        canvas.setFillColor(HexColor('#666666'))
        
        # Calcular informações da página atual
        page_num = canvas.getPageNumber()
        sensores_por_pagina = 7
        fim_sensor = min(page_num * sensores_por_pagina, total_sensores)
        
        # Construir texto do rodapé em partes para evitar sobreposição
        canvas.setFont("Helvetica-Bold", 8)
        
        # Calcular larguras para posicionamento correto
        numero_atual = str(fim_sensor)
        de_text = " de "
        total_text = str(total_sensores)
        sensores_text = " sensores | "
        pagina_text = f"Página {page_num}"
        
        # Larguras dos elementos
        w_numero = canvas.stringWidth(numero_atual, "Helvetica-Bold", 8)
        w_de = canvas.stringWidth(de_text, "Helvetica", 8)
        w_total = canvas.stringWidth(total_text, "Helvetica-Bold", 8)
        w_sensores = canvas.stringWidth(sensores_text, "Helvetica", 8)
        w_pagina = canvas.stringWidth(pagina_text, "Helvetica", 8)
        
        # Posição inicial (canto direito)
        x_pos = A4[0] - 40
        
        # Desenhar elementos da direita para a esquerda
        # 1. "Página X" (normal)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawRightString(x_pos, 30, pagina_text)
        x_pos -= w_pagina
        
        # 2. " sensores | " (normal)
        canvas.drawRightString(x_pos, 30, sensores_text)
        x_pos -= w_sensores
        
        # 3. Total (negrito)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawRightString(x_pos, 30, total_text)
        x_pos -= w_total
        
        # 4. " de " (normal)
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(x_pos, 30, de_text)
        x_pos -= w_de
        
        # 5. Número atual (negrito)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawRightString(x_pos, 30, numero_atual)
        
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_rounded_border_and_footer, onLaterPages=draw_rounded_border_and_footer)
    output.seek(0)

    return send_file(
        output,
        download_name=f'relatorio_{municipio or "todos"}_{valor_classificacao or "todos"}.pdf',
        as_attachment=True,
        mimetype='application/pdf'
    )

if __name__ == '__main__':
    app.run(debug=True)
