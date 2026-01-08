import streamlit as st
import pandas as pd
import time
import os
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Diagnóstico", page_icon="🔧", layout="wide")

# =============================================================================
# SETUP DO DRIVER (CORREÇÃO DE CAMINHOS LINUX)
# =============================================================================
def get_driver():
    """Inicializa o driver usando os binários do sistema Linux (Streamlit Cloud)"""
    
    # 1. Definição de Caminhos Padrão do Debian/Linux
    CHROMIUM_PATH = "/usr/bin/chromium"
    DRIVER_PATH = "/usr/bin/chromedriver"
    
    # 2. Diagnóstico de Arquivos (Evita o erro silencioso)
    if not os.path.exists(CHROMIUM_PATH):
        st.error(f"ERRO FATAL: O navegador não foi encontrado em {CHROMIUM_PATH}. Verifique o arquivo packages.txt")
        return None
    if not os.path.exists(DRIVER_PATH):
        st.error(f"ERRO FATAL: O driver não foi encontrado em {DRIVER_PATH}. Verifique o arquivo packages.txt")
        return None

    # 3. Configuração das Opções
    chrome_options = Options()
    chrome_options.binary_location = CHROMIUM_PATH
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    try:
        service = Service(DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        st.error(f"Erro ao iniciar o Selenium: {str(e)}")
        return None

# =============================================================================
# LÓGICA DE LOGIN (BASEADA NO SEU SCRIPT LOCAL)
# =============================================================================
def realizar_login(driver, usuario, senha):
    status_msg = st.empty()
    status_msg.info("Acessando página de login...")
    
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 20)
        actions = ActionChains(driver)

        # --- Passo 1: Usuário ---
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        
        # Garante foco e digitação
        actions.move_to_element(campo_user).click().perform()
        campo_user.clear()
        campo_user.send_keys(usuario)

        # --- Passo 2: Botão OK ---
        driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk").click()
        
        status_msg.info("Aguardando carregamento...")
        time.sleep(3) # Pausa obrigatória do seu script local

        # --- Passo 3: Senha (Se necessário) ---
        try:
            xpath_senha = "//input[@type='password']"
            if len(driver.find_elements(By.XPATH, xpath_senha)) > 0:
                status_msg.info("Inserindo senha...")
                campo_senha = driver.find_element(By.XPATH, xpath_senha)
                
                # Clica, Limpa, Digita, Enter (Padrão robusto)
                actions.move_to_element(campo_senha).click().perform()
                campo_senha.clear()
                campo_senha.send_keys(senha)
                time.sleep(1)
                campo_senha.send_keys(Keys.RETURN)
        except Exception as e:
            pass # Segue o fluxo

        # --- Passo 4: Validação ---
        status_msg.info("Verificando acesso...")
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        status_msg.empty()
        return True

    except Exception as e:
        status_msg.error(f"Falha no login: {e}")
        try: st.image(driver.get_screenshot_as_png(), caption="Erro Login")
        except: pass
        return False

# =============================================================================
# LÓGICA DE EXTRAÇÃO (ADAPTADA DO SEU SCRIPT LOCAL)
# =============================================================================
def esperar_preenchimento(driver, element_id, timeout=10):
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            val = driver.find_element(By.ID, element_id).get_attribute('value')
            if val and val.strip(): return val
        except: pass
        time.sleep(0.5)
    return ""

def processar_auto(driver, auto):
    res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 20)
    main_window = driver.current_window_handle
    
    try:
        # 1. Busca
        campo = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        campo.clear()
        campo.send_keys(auto)
        
        # 2. Clicar Pesquisar
        encontrou = False
        for _ in range(3):
            try:
                btn = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                
                # Verifica sucesso ou erro
                if "Nenhum registro" in driver.page_source: break
                wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")))
                encontrou = True
                break
            except: time.sleep(1)
        
        if not encontrou:
            res['status'] = 'nao_encontrado'
            res['mensagem'] = 'Auto não localizado'
            return res

        # 3. Abrir Popup
        btn_edit = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_edit)
        
        # 4. Trocar Janela
        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))
        for w in driver.window_handles:
            if w != main_window: driver.switch_to.window(w)
        
        time.sleep(3) # Espera do seu script local
        
        # 5. Extração
        d = {}
        try:
            id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
            
            d['processo'] = esperar_preenchimento(driver, id_proc)
            if not d['processo']: d['processo'] = driver.find_element(By.ID, id_proc).get_attribute('value')

            d['data_inf'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao").get_attribute('value')
            d['codigo'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao").get_attribute('value')
            d['fato'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao").get_attribute('value')

            # Tabela
            try:
                xp = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                tab = driver.find_element(By.XPATH, xp)
                trs = tab.find_elements(By.TAG_NAME, "tr")
                if len(trs) > 1:
                    tds = trs[-1].find_elements(By.TAG_NAME, "td")
                    # Lógica da 4ª Coluna
                    if len(tds) >= 4:
                        d['dt_andamento'] = tds[3].text
                        d['andamento'] = tds[1].text
                    elif len(tds) >= 2:
                        d['dt_andamento'] = tds[-1].text
                        d['andamento'] = tds[0].text
            except:
                d['andamento'] = 'Sem andamentos'
                
            res['status'] = 'sucesso'
            res['dados'] = d
            res['mensagem'] = 'Sucesso'

        except Exception as e:
            res['mensagem'] = f'Erro Leitura: {e}'

        driver.close()
        driver.switch_to.window(main_window)
        return res

    except Exception as e:
        res['mensagem'] = f'Erro Fluxo: {e}'
        if len(driver.window_handles) > 1:
            try: driver.switch_to.window(main_window)
            except: pass
        return res

# =============================================================================
# INTERFACE GRÁFICA
# =============================================================================
st.title("🚛 Robô ANTT - Diagnóstico & Correção")

col1, col2 = st.columns(2)
with col1: usuario = st.text_input("Usuário")
with col2: senha = st.text_input("Senha", type="password")

arquivo = st.file_uploader("Planilha (.xlsx)", type="xlsx")

if st.button("🚀 INICIAR CONSULTA") and arquivo and usuario:
    # Mostra mensagem de início imediata para você saber que o botão funcionou
    st.info("Iniciando processo... Verificando drivers...")
    
    try:
        # Preparação
        df = pd.read_excel(arquivo)
        cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
        for c in cols:
            if c not in df.columns: df[c] = ""
        df = df.astype(object).replace('nan', '')

        # Init Driver
        driver = get_driver()
        
        if driver:
            if realizar_login(driver, usuario, senha):
                st.success("Login Conectado! Iniciando varredura...")
                
                progresso = st.progress(0)
                status_txt = st.empty()
                tabela_preview = st.empty()
                
                total = len(df)
                for idx, row in df.iterrows():
                    auto = str(row['Auto de Infração']).strip()
                    if not auto or auto == 'nan': continue
                    
                    status_txt.text(f"Consultando [{idx+1}/{total}]: {auto}")
                    
                    res = processar_auto(driver, auto)
                    
                    df.at[idx, 'Status Consulta'] = str(res['mensagem'])
                    if res['status'] == 'sucesso':
                        d = res['dados']
                        df.at[idx, 'Nº do Processo'] = str(d.get('processo', ''))
                        df.at[idx, 'Data da Infração'] = str(d.get('data_inf', ''))
                        df.at[idx, 'Código da Infração'] = str(d.get('codigo', ''))
                        df.at[idx, 'Fato Gerador'] = str(d.get('fato', ''))
                        df.at[idx, 'Último Andamento'] = str(d.get('andamento', ''))
                        df.at[idx, 'Data do Último Andamento'] = str(d.get('dt_andamento', ''))
                    
                    progresso.progress((idx+1)/total)
                    tabela_preview.dataframe(df.head(idx+1)) # Feedback visual simples
                
                # Salva na sessão para o botão não sumir
                st.session_state['df_final'] = df
                st.success("Concluído!")
            else:
                st.error("Login falhou. Verifique se o usuário/senha estão corretos.")
            
            driver.quit()
        else:
            st.error("Falha ao criar o driver. O script parou.")

    except Exception as e:
        st.error(f"Erro Fatal na Execução: {e}")

# Botão de Download Persistente
if 'df_final' in st.session_state:
    st.write("---")
    buffer = BytesIO()
    st.session_state['df_final'].to_excel(buffer, index=False)
    buffer.seek(0)
    st.download_button("📥 Baixar Planilha Final", data=buffer, file_name="Resultado_ANTT.xlsx")
