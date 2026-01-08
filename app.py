import streamlit as st
import pandas as pd
import time
import traceback
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
# CONFIGURAÇÃO GERAL
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Blindado", page_icon="🛡️", layout="wide")

# Área de logs na interface
if 'logs' not in st.session_state:
    st.session_state.logs = []

def log_message(msg):
    """Função para adicionar mensagens ao log visual"""
    timestamp = time.strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg) # Log no console do servidor
    st.session_state.logs.append(formatted_msg)
    # Mantém apenas os últimos 10 logs na tela para economizar memória visual
    if len(st.session_state.logs) > 10:
        st.session_state.logs.pop(0)

# =============================================================================
# SETUP DO DRIVER (LINUX/CLOUD)
# =============================================================================
def get_driver():
    chrome_options = Options()
    chrome_options.binary_location = "/usr/bin/chromium"
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage") # Vital para não estourar memória
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        # Fallback caso o path seja diferente
        return webdriver.Chrome(options=chrome_options)

# =============================================================================
# FUNÇÕES DE LOGIN E VERIFICAÇÃO DE SESSÃO
# =============================================================================

def verificar_sessao_ativa(driver):
    """Verifica se o usuário ainda está logado procurando o campo de busca"""
    try:
        # Tenta achar o campo de busca com timeout curto (3s)
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao"))
        )
        return True
    except:
        return False

def realizar_login(driver, usuario, senha):
    """Faz o login (ou relogin) no sistema"""
    log_message("Tentando realizar login...")
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
        
        time.sleep(3) # Espera postback

        # 3. Senha (se pedir)
        try:
            xpath_senha = "//input[@type='password']"
            wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
            campo_senha = driver.find_element(By.XPATH, xpath_senha)
            
            actions.move_to_element(campo_senha).click().perform()
            campo_senha.clear()
            campo_senha.send_keys(senha)
            time.sleep(1)
            campo_senha.send_keys(Keys.RETURN)
        except:
            pass # Pode ser login sem senha

        # 4. Validação
        if verificar_sessao_ativa(driver):
            log_message("Login realizado com sucesso!")
            return True
        else:
            log_message("Falha: Login não detectado após tentativas.")
            return False

    except Exception as e:
        log_message(f"Erro crítico no login: {e}")
        return False

# =============================================================================
# FUNÇÕES DE EXTRAÇÃO
# =============================================================================

def esperar_valor_campo(driver, element_id, timeout=8):
    """Espera inteligente para valor do campo"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            val = driver.find_element(By.ID, element_id).get_attribute('value')
            if val and val.strip(): return val
        except: pass
        time.sleep(0.5)
    return ""

def consultar_auto(driver, auto):
    res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 15) # Timeout reduzido para não travar muito
    janela_main = driver.current_window_handle
    
    try:
        # 1. Tenta Limpar e Inserir
        try:
            campo = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
            campo.clear()
            campo.send_keys(auto)
        except:
            # Se falhar aqui, provavelmente a sessão caiu
            raise Exception("Sessão Expirada")

        # 2. Pesquisar
        encontrou = False
        for _ in range(2): # 2 Tentativas
            try:
                btn = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                
                # Verifica botão editar OU mensagem de erro
                if "Nenhum registro" in driver.page_source:
                    break
                
                wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")))
                encontrou = True
                break
            except:
                time.sleep(1)
        
        if not encontrou:
            res['status'] = 'nao_encontrado'
            res['mensagem'] = 'Auto não localizado'
            return res

        # 3. Abrir Popup
        btn_edit = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_edit)
        
        # 4. Janelas
        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        for w in driver.window_handles:
            if w != janela_main: driver.switch_to.window(w)
        
        time.sleep(2.5) # Pausa para carregamento dos dados
        
        # 5. Extração
        d = {}
        try:
            id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
            
            d['processo'] = esperar_valor_campo(driver, id_proc)
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
            res['mensagem'] = f'Erro Extração: {str(e)[:50]}'

        driver.close()
        driver.switch_to.window(janela_main)
        return res

    except Exception as e:
        if "Sessão Expirada" in str(e):
            raise e # Joga o erro pra cima para fazer relogin
        
        res['mensagem'] = f'Erro Fluxo: {str(e)[:50]}'
        # Tenta recuperar janela
        if len(driver.window_handles) > 1:
            try: driver.switch_to.window(janela_main)
            except: pass
        return res

# =============================================================================
# INTERFACE PRINCIPAL
# =============================================================================
st.title("🛡️ Robô ANTT - Consulta Robusta")

col1, col2 = st.columns(2)
with col1: usuario = st.text_input("Usuário ANTT")
with col2: senha = st.text_input("Senha ANTT", type="password")

uploaded_file = st.file_uploader("Planilha de Entrada (.xlsx)", type="xlsx")

# Container para os logs dinâmicos
log_container = st.empty()

if st.button("🚀 Iniciar Processamento Blindado") and uploaded_file and usuario:
    # 1. Preparação
    df = pd.read_excel(uploaded_file)
    cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
            'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
    for c in cols:
        if c not in df.columns: df[c] = ""
    df = df.astype(object).replace('nan', '')

    st.session_state.df_parcial = df # Backup na sessão
    
    # 2. Inicialização do Driver
    driver = get_driver()
    
    # 3. Login Inicial
    if realizar_login(driver, usuario, senha):
        
        progress_bar = st.progress(0)
        total_rows = len(df)
        driver_restart_count = 0
        
        # ================= LOOP PRINCIPAL =================
        for idx, row in df.iterrows():
            try:
                # Atualiza Logs na Tela
                log_text = "\n".join(st.session_state.logs)
                log_container.text_area("Log de Execução (Últimos eventos):", log_text, height=200)
                
                auto = str(row['Auto de Infração']).strip()
                if not auto or auto == 'nan': continue

                log_message(f"[{idx+1}/{total_rows}] Processando: {auto}")

                # --- GESTÃO DE MEMÓRIA (REINICIA O BROWSER A CADA 20 CONSULTAS) ---
                if driver_restart_count >= 20:
                    log_message("⚠️ Limpeza de Memória: Reiniciando navegador...")
                    driver.quit()
                    time.sleep(2)
                    driver = get_driver()
                    realizar_login(driver, usuario, senha)
                    driver_restart_count = 0

                # --- VERIFICAÇÃO DE SESSÃO ---
                if not verificar_sessao_ativa(driver):
                    log_message("⚠️ Sessão caiu! Tentando reconectar...")
                    if not realizar_login(driver, usuario, senha):
                        log_message("❌ Não foi possível reconectar. Parando.")
                        break
                
                # --- CONSULTA ---
                try:
                    res = consultar_auto(driver, auto)
                except Exception as e:
                    # Se deu erro de sessão durante a consulta, tenta uma vez mais
                    if "Sessão Expirada" in str(e):
                        log_message("Sessão expirou durante consulta. Reconectando...")
                        realizar_login(driver, usuario, senha)
                        res = consultar_auto(driver, auto)
                    else:
                        res = {'status': 'erro', 'mensagem': f'Erro fatal: {e}'}

                # --- SALVAR RESULTADOS ---
                df.at[idx, 'Status Consulta'] = str(res['mensagem'])
                
                if res['status'] == 'sucesso':
                    d = res['dados']
                    df.at[idx, 'Nº do Processo'] = str(d.get('processo', ''))
                    df.at[idx, 'Data da Infração'] = str(d.get('data_inf', ''))
                    df.at[idx, 'Código da Infração'] = str(d.get('codigo', ''))
                    df.at[idx, 'Fato Gerador'] = str(d.get('fato', ''))
                    df.at[idx, 'Último Andamento'] = str(d.get('andamento', ''))
                    df.at[idx, 'Data do Último Andamento'] = str(d.get('dt_andamento', ''))
                    log_message(f"✅ Sucesso: {auto}")
                else:
                    log_message(f"⚠️ {res['mensagem']}")

                # Atualiza progresso e contadores
                progress_bar.progress((idx + 1) / total_rows)
                driver_restart_count += 1
                
                # Salva backup na sessão do Streamlit a cada linha (segurança)
                st.session_state.df_parcial = df

            except Exception as e_loop:
                log_message(f"❌ Erro na linha {idx}: {e_loop}")
                continue # Não para o script, vai para o próximo auto

        # ================= FIM DO LOOP =================
        log_message("🏁 Processamento finalizado!")
        driver.quit()
        
    else:
        st.error("Não foi possível iniciar. Falha no Login.")

# --- ÁREA DE DOWNLOAD (PERSISTENTE) ---
if 'df_parcial' in st.session_state:
    st.write("---")
    st.success("Tabela processada disponível para download.")
    
    buffer = BytesIO()
    st.session_state.df_parcial.to_excel(buffer, index=False)
    buffer.seek(0)
    
    st.download_button(
        label="📥 Baixar Planilha Final",
        data=buffer,
        file_name="Resultado_ANTT_Blindado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
