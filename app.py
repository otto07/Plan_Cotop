import streamlit as st
import pandas as pd
import time
import os
import shutil
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# =============================================================================
# CONFIGURAÇÃO VISUAL
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Logs", page_icon="⚙️", layout="wide")

if 'logs' not in st.session_state:
    st.session_state.logs = []

def log_message(msg):
    """Adiciona mensagem ao log visual e ao console"""
    timestamp = time.strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    st.session_state.logs.append(formatted_msg)

# =============================================================================
# SETUP DO DRIVER (AUTO-DETECÇÃO)
# =============================================================================
def get_driver():
    """Configuração híbrida: Tenta usar o do sistema, se falhar, usa o Manager"""
    chrome_options = Options()
    
    # 1. Tenta encontrar onde o Chromium está instalado no Linux
    chrome_bin = shutil.which("chromium") or shutil.which("chromium-browser") or "/usr/bin/chromium"
    log_message(f"Binário do Chrome detectado em: {chrome_bin}")
    
    chrome_options.binary_location = chrome_bin
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    # TENTATIVA 1: Usar o driver do sistema (instalado via packages.txt)
    try:
        log_message("Tentando iniciar driver do sistema...")
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        log_message("Driver do sistema iniciado com sucesso!")
        return driver
    except Exception as e1:
        log_message(f"Driver do sistema falhou ({e1}). Tentando Webdriver Manager...")
        
        # TENTATIVA 2: Baixar um driver compatível automaticamente
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            log_message("Driver do Manager iniciado com sucesso!")
            return driver
        except Exception as e2:
            st.error(f"FATAL: Não foi possível iniciar nenhum navegador. Erro: {e2}")
            raise e2

# =============================================================================
# LÓGICA DE NEGÓCIO (LOGIN E EXTRAÇÃO)
# =============================================================================

def realizar_login_robusto(driver, usuario, senha):
    log_message("Acessando página de login...")
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 20)
        actions = ActionChains(driver)

        # 1. Usuário
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        actions.move_to_element(campo_user).click().perform()
        campo_user.clear()
        campo_user.send_keys(usuario)

        # 2. OK Inicial
        driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk").click()
        
        log_message("Aguardando recarregamento da página (3s)...")
        time.sleep(3) 

        # 3. Senha (Injeção JS + ActionChains)
        try:
            xpath_senha = "//input[@type='password']"
            if len(driver.find_elements(By.XPATH, xpath_senha)) > 0:
                campo_senha = driver.find_element(By.XPATH, xpath_senha)
                
                # Clica e Digita
                actions.move_to_element(campo_senha).click().perform()
                campo_senha.clear()
                campo_senha.send_keys(senha)
                
                # Garante valor via JS
                driver.execute_script(f"arguments[0].value = '{senha}';", campo_senha)
                
                time.sleep(0.5)
                campo_senha.send_keys(Keys.RETURN)
        except Exception as e:
            log_message(f"Aviso no campo senha: {e}")

        # 4. Validação
        log_message("Validando acesso...")
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        return True

    except Exception as e:
        log_message(f"Erro no Login: {e}")
        return False

def consultar_auto(driver, auto):
    res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 15)
    janela_main = driver.current_window_handle
    
    try:
        # Busca
        try:
            campo = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
            campo.clear()
            campo.send_keys(auto)
        except:
            raise Exception("Sessão Queda") # Gatilho para relogin

        # Pesquisar
        encontrou = False
        for _ in range(2):
            try:
                btn = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                if "Nenhum registro" in driver.page_source: break
                wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")))
                encontrou = True
                break
            except: time.sleep(1)
        
        if not encontrou:
            res['status'] = 'nao_encontrado'
            res['mensagem'] = 'Auto não localizado'
            return res

        # Popup
        btn_edit = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_edit)
        
        # Janelas
        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        for w in driver.window_handles:
            if w != janela_main: driver.switch_to.window(w)
        
        time.sleep(2) 
        
        # Extração
        d = {}
        try:
            id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
            
            # Helper para pegar valor
            def get_val(id_elem):
                try: return driver.find_element(By.ID, id_elem).get_attribute('value')
                except: return ""

            d['processo'] = get_val(id_proc)
            d['data_inf'] = get_val("ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao")
            d['codigo'] = get_val("ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao")
            d['fato'] = get_val("ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao")

            try:
                xp = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                tab = driver.find_element(By.XPATH, xp)
                trs = tab.find_elements(By.TAG_NAME, "tr")
                if len(trs) > 1:
                    tds = trs[-1].find_elements(By.TAG_NAME, "td")
                    if len(tds) >= 4:
                        d['dt_andamento'] = tds[3].text
                        d['andamento'] = tds[1].text
                    elif len(tds) >= 2:
                        d['dt_andamento'] = tds[-1].text
                        d['andamento'] = tds[0].text
            except: d['andamento'] = 'Sem andamentos'
            
            res['status'] = 'sucesso'
            res['dados'] = d
            res['mensagem'] = 'Sucesso'

        except Exception as e:
            res['mensagem'] = f'Erro Leitura: {e}'

        driver.close()
        driver.switch_to.window(janela_main)
        return res

    except Exception as e:
        if "Sessão Queda" in str(e): raise e
        res['mensagem'] = f'Erro Fluxo: {str(e)[:30]}'
        if len(driver.window_handles) > 1:
            try: driver.switch_to.window(janela_main)
            except: pass
        return res

# =============================================================================
# INTERFACE PRINCIPAL
# =============================================================================
st.title("🛡️ Robô ANTT - Modo Log")

col1, col2 = st.columns(2)
with col1: usuario = st.text_input("Usuário ANTT")
with col2: senha = st.text_input("Senha ANTT", type="password")

uploaded_file = st.file_uploader("Planilha de Entrada (.xlsx)", type="xlsx")

# Área de logs
log_box = st.empty()

# Botão principal
if st.button("🚀 INICIAR CONSULTA"):
    if not uploaded_file or not usuario:
        st.warning("Preencha usuário e suba a planilha.")
    else:
        st.session_state.logs = [] # Limpa logs antigos
        log_message("Inicializando script...")
        
        try:
            # 1. Carrega Planilha
            df = pd.read_excel(uploaded_file)
            cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                    'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
            for c in cols:
                if c not in df.columns: df[c] = ""
            df = df.astype(object).replace('nan', '')
            
            st.session_state.df_final = df # Backup inicial
            
            # 2. Inicia Driver
            driver = get_driver()
            
            # 3. Login
            if realizar_login_robusto(driver, usuario, senha):
                log_message("Login OK. Iniciando loop...")
                
                total = len(df)
                restart_counter = 0
                
                progress_text = st.empty()
                bar = st.progress(0)
                
                for idx, row in df.iterrows():
                    # Mostra log na tela
                    log_box.text_area("Logs de Execução:", "\n".join(st.session_state.logs[-15:]), height=300)
                    
                    auto = str(row['Auto de Infração']).strip()
                    if not auto or auto == 'nan': continue
                    
                    progress_text.text(f"Processando {idx+1}/{total}: {auto}")
                    
                    # Gestão de Memória
                    if restart_counter >= 30:
                        log_message("Reiniciando navegador (Memória)...")
                        driver.quit()
                        driver = get_driver()
                        realizar_login_robusto(driver, usuario, senha)
                        restart_counter = 0

                    # Executa Consulta
                    try:
                        res = consultar_auto(driver, auto)
                    except Exception as e:
                        if "Sessão" in str(e):
                            log_message("Sessão caiu. Relogando...")
                            realizar_login_robusto(driver, usuario, senha)
                            res = consultar_auto(driver, auto)
                        else:
                            res = {'status': 'erro', 'mensagem': f'Erro: {e}'}

                    # Salva
                    df.at[idx, 'Status Consulta'] = str(res['mensagem'])
                    if res['status'] == 'sucesso':
                        d = res['dados']
                        df.at[idx, 'Nº do Processo'] = str(d.get('processo', ''))
                        df.at[idx, 'Data da Infração'] = str(d.get('data_inf', ''))
                        df.at[idx, 'Código da Infração'] = str(d.get('codigo', ''))
                        df.at[idx, 'Fato Gerador'] = str(d.get('fato', ''))
                        df.at[idx, 'Último Andamento'] = str(d.get('andamento', ''))
                        df.at[idx, 'Data do Último Andamento'] = str(d.get('dt_andamento', ''))
                        log_message(f"OK: {auto}")
                    else:
                        log_message(f"Falha {auto}: {res['mensagem']}")
                    
                    st.session_state.df_final = df # Salva na sessão
                    restart_counter += 1
                    bar.progress((idx+1)/total)

                log_message("Fim do processamento.")
                driver.quit()
                st.success("Concluído!")
                
            else:
                st.error("Login falhou. Verifique logs.")
                driver.quit()

        except Exception as e:
            st.error(f"Erro Fatal: {e}")
            log_message(f"CRASH: {e}")

# Botão de Download (Persistente)
if 'df_final' in st.session_state:
    st.write("---")
    buffer = BytesIO()
    st.session_state.df_final.to_excel(buffer, index=False)
    buffer.seek(0)
    st.download_button("📥 BAIXAR PLANILHA FINAL", data=buffer, file_name="Resultado_ANTT.xlsx")
