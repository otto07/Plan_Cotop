import streamlit as st
import pandas as pd
import time
import os
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="Robô ANTT - Consulta Web",
    page_icon="🚛",
    layout="wide"
)

# =============================================================================
# FUNÇÕES CORE (SELENIUM ADAPTADO PARA LINUX/CLOUD)
# =============================================================================

def get_driver():
    """Inicia o navegador compatível com Streamlit Cloud (Linux)"""
    chrome_options = Options()
    
    # Flags OBRIGATÓRIAS para rodar em container Linux/Docker/Cloud
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-features=NetworkService")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detecção básico
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    # Tenta usar o driver instalado pelo webdriver-manager
    # Em ambiente Linux Cloud (como Streamlit), o chromium-driver já estará no PATH
    # graças ao arquivo packages.txt
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        # Fallback para o driver do sistema (caso o manager falhe no cloud)
        driver = webdriver.Chrome(options=chrome_options)
        
    return driver

def realizar_login_automatico(driver, usuario, senha):
    """Realiza login automatizado"""
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 15)

        # 1. Inserir Usuário
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        campo_user.clear()
        campo_user.send_keys(usuario)

        # 2. Clicar OK
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        btn_ok = driver.find_element(By.ID, id_btn_ok)
        btn_ok.click()
        
        # 3. Tratamento de Senha (se aparecer)
        try:
            time.sleep(2)
            campo_senha = driver.find_element(By.XPATH, "//input[@type='password']")
            if campo_senha.is_displayed():
                campo_senha.clear()
                campo_senha.send_keys(senha)
                btn_ok.click()
        except:
            pass
            
        # 4. Verificar sucesso
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        return True
    except Exception as e:
        st.error(f"Erro no login: {str(e)}")
        return False

def esperar_dados_preenchidos(driver, element_id, timeout=10):
    """Espera o valor aparecer no input"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            elem = driver.find_element(By.ID, element_id)
            valor = elem.get_attribute('value')
            if valor and valor.strip() != "":
                return valor
            time.sleep(0.5)
        except:
            pass
    return ""

def processar_auto(driver, auto_infracao):
    """Lógica principal de extração"""
    resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 20)
    janela_principal = driver.current_window_handle
    
    try:
        # 1. Busca
        campo_busca = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        campo_busca.clear()
        campo_busca.send_keys(auto_infracao)
        
        # 2. Pesquisar (Retry + JS Click)
        encontrou = False
        for tentativa in range(3):
            try:
                btn_pesquisar = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
                driver.execute_script("arguments[0].click();", btn_pesquisar)
                time.sleep(2)
                
                # Verifica botão editar
                wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")))
                encontrou = True
                break
            except:
                if "Nenhum registro encontrado" in driver.page_source:
                    break
        
        if not encontrou:
            resultado['status'] = 'nao_encontrado'
            resultado['mensagem'] = 'Auto não localizado'
            return resultado

        # 3. Abrir Pop-up
        btn_editar = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_editar)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_editar)
        
        # 4. Troca de Janela
        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))
        janelas = driver.window_handles
        nova_janela = [j for j in janelas if j != janela_principal][0]
        driver.switch_to.window(nova_janela)
        time.sleep(3) # Espera técnica
        
        # 5. Extração
        dados = {}
        try:
            id_processo = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            
            # Garante que carregou
            wait.until(EC.visibility_of_element_located((By.ID, id_processo)))
            dados['processo'] = esperar_dados_preenchidos(driver, id_processo)
            
            if not dados['processo']:
                 dados['processo'] = driver.find_element(By.ID, id_processo).get_attribute('value')

            dados['data_infracao'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao").get_attribute('value')
            dados['codigo'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao").get_attribute('value')
            dados['fato'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao").get_attribute('value')

            # Tabela de Andamentos
            try:
                xpath_tabela = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                wait.until(EC.presence_of_element_located((By.XPATH, xpath_tabela)))
                tabela = driver.find_element(By.XPATH, xpath_tabela)
                linhas = tabela.find_elements(By.TAG_NAME, "tr")
                
                if len(linhas) > 1:
                    ultima_linha = linhas[-1]
                    cols = ultima_linha.find_elements(By.TAG_NAME, "td")
                    if len(cols) >= 4:
                        dados['data_andamento'] = cols[3].text
                        dados['andamento'] = cols[1].text
                    elif len(cols) >= 2:
                        dados['data_andamento'] = cols[-1].text
                        dados['andamento'] = cols[0].text
                    else:
                         dados['andamento'] = 'Tabela não padrão'
            except:
                dados['andamento'] = 'Sem andamentos'
                
            resultado['status'] = 'sucesso'
            resultado['dados'] = dados
            resultado['mensagem'] = 'Sucesso'

        except Exception as e:
            resultado['mensagem'] = f'Erro leitura: {str(e)}'

        driver.close()
        driver.switch_to.window(janela_principal)
        return resultado

    except Exception as e:
        resultado['mensagem'] = f'Erro fluxo: {str(e)}'
        if len(driver.window_handles) > 1:
            try: driver.switch_to.window(janela_principal)
            except: pass
        return resultado

# =============================================================================
# INTERFACE STREAMLIT
# =============================================================================

st.title("🚛 Robô ANTT - Consulta Web (Cloud)")

tab1, tab2 = st.tabs(["🔍 Consulta Automática", "📊 Comparação de Planilhas"])

# --- ABA 1: CONSULTA ---
with tab1:
    st.info("Sistema configurado para rodar em nuvem (Headless).")
    
    col1, col2 = st.columns(2)
    with col1:
        usuario = st.text_input("Usuário ANTT")
    with col2:
        senha = st.text_input("Senha ANTT", type="password")
    
    uploaded_file = st.file_uploader("Carregar planilha (.xlsx)", type="xlsx", key="upload_main")
    
    if st.button("🚀 Iniciar Processamento") and uploaded_file and usuario:
        try:
            df = pd.read_excel(uploaded_file)
            
            # Garantir colunas
            cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                    'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
            for c in cols:
                if c not in df.columns: df[c] = ""
            
            df = df.astype(object).replace('nan', '')

            # Elementos de UI
            progresso = st.progress(0)
            status_txt = st.empty()
            preview = st.empty()
            
            driver = get_driver()
            
            status_txt.text("Iniciando login no sistema...")
            if realizar_login_automatico(driver, usuario, senha):
                st.success("Login bem-sucedido!")
                
                total = len(df)
                for index, row in df.iterrows():
                    auto = str(row['Auto de Infração']).strip()
                    if pd.isna(auto) or auto == '' or auto == 'nan': continue
                    
                    status_txt.text(f"Consultando [{index+1}/{total}]: {auto}...")
                    
                    res = processar_auto(driver, auto)
                    
                    df.at[index, 'Status Consulta'] = str(res['mensagem'])
                    if res['status'] == 'sucesso':
                        d = res['dados']
                        df.at[index, 'Nº do Processo'] = str(d.get('processo', ''))
                        df.at[index, 'Data da Infração'] = str(d.get('data_infracao', ''))
                        df.at[index, 'Código da Infração'] = str(d.get('codigo', ''))
                        df.at[index, 'Fato Gerador'] = str(d.get('fato', ''))
                        df.at[index, 'Último Andamento'] = str(d.get('andamento', ''))
                        df.at[index, 'Data do Último Andamento'] = str(d.get('data_andamento', ''))
                    
                    progresso.progress((index + 1) / total)
                    preview.dataframe(df.head(index + 1))
                
                status_txt.text("Finalizado!")
                
                # Download
                buffer = BytesIO()
                df.to_excel(buffer, index=False)
                buffer.seek(0)
                st.download_button("📥 Baixar Resultado", data=buffer, file_name="Resultado_ANTT.xlsx")
            else:
                st.error("Falha no login. Verifique as credenciais.")
            
            driver.quit()

        except Exception as e:
            st.error(f"Erro: {e}")

# --- ABA 2: COMPARAÇÃO ---
with tab2:
    st.header("Comparação de Planilhas")
    
    col_a, col_b = st.columns(2)
    with col_a:
        f_antigo = st.file_uploader("Planilha Antiga", type=["xlsx"], key="antiga")
    with col_b:
        f_novo = st.file_uploader("Planilha Nova", type=["xlsx"], key="nova")

    if st.button("Comparar") and f_antigo and f_novo:
        try:
            df_old = pd.read_excel(f_antigo)
            df_new = pd.read_excel(f_novo)
            
            if "Auto de Infração" in df_old.columns and "Auto de Infração" in df_new.columns:
                df_old = df_old.rename(columns={"Último Andamento": "Status_Ant", "Data do Último Andamento": "Data_Ant"})
                df_new = df_new.rename(columns={"Último Andamento": "Status_Nov", "Data do Último Andamento": "Data_Nov"})
                
                df_res = pd.merge(df_new, df_old[['Auto de Infração', 'Status_Ant', 'Data_Ant']], on='Auto de Infração', how='left')
                
                def check_change(row):
                    s1, s2 = str(row['Status_Ant']).strip(), str(row['Status_Nov']).strip()
                    if pd.isna(row['Status_Ant']) or s1 in ['nan', '']: return "Novo"
                    return "Mudou" if s1 != s2 else "Igual"

                df_res['Resultado'] = df_res.apply(check_change, axis=1)
                mudancas = df_res[df_res['Resultado'] == "Mudou"]
                
                st.metric("Processos alterados", len(mudancas))
                st.dataframe(mudancas)
                
                b = BytesIO()
                df_res.to_excel(b, index=False)
                b.seek(0)
                st.download_button("📥 Baixar Relatório", data=b, file_name="Relatorio_Comparacao.xlsx")
            else:
                st.error("Coluna 'Auto de Infração' não encontrada.")
        except Exception as e:
            st.error(f"Erro: {e}")
