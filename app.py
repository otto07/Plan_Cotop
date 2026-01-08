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
st.set_page_config(page_title="Robô ANTT - Final", page_icon="🚛", layout="wide")

# Inicializa o estado da sessão para guardar o arquivo final
if 'df_resultado' not in st.session_state:
    st.session_state.df_resultado = None

# =============================================================================
# SETUP DO DRIVER
# =============================================================================
def get_driver():
    chrome_options = Options()
    chrome_options.binary_location = "/usr/bin/chromium"
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception:
        return webdriver.Chrome(options=chrome_options)

# =============================================================================
# FUNÇÕES DE LÓGICA (LOGIN E EXTRAÇÃO)
# =============================================================================
def realizar_login_debug(driver, usuario, senha):
    status = st.empty()
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 20)
        actions = ActionChains(driver)

        # 1. Usuário
        status.info("Inserindo usuário...")
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        actions.move_to_element(campo_user).click().perform()
        campo_user.clear()
        campo_user.send_keys(usuario)

        # 2. OK Inicial
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        driver.find_element(By.ID, id_btn_ok).click()
        
        status.info("Aguardando sistema...")
        time.sleep(3) 

        # 3. Senha
        status.info("Inserindo senha...")
        try:
            xpath_senha = "//input[@type='password']"
            wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
            campo_senha = driver.find_element(By.XPATH, xpath_senha)
            
            actions.move_to_element(campo_senha).click().perform()
            campo_senha.clear()
            campo_senha.send_keys(senha)
            time.sleep(1)
            campo_senha.send_keys(Keys.RETURN)
            
        except Exception:
            pass

        # 4. Validação
        status.info("Validando acesso...")
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        status.empty()
        return True

    except Exception as e:
        status.error("Erro no login.")
        try: st.image(driver.get_screenshot_as_png()) 
        except: pass
        return False

def esperar_dados(driver, element_id, timeout=10):
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            val = driver.find_element(By.ID, element_id).get_attribute('value')
            if val and val.strip(): return val
            time.sleep(0.5)
        except: pass
    return ""

def processar_auto(driver, auto):
    res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 20)
    janela_main = driver.current_window_handle
    
    try:
        campo = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        campo.clear()
        campo.send_keys(auto)
        
        encontrou = False
        for _ in range(3):
            try:
                btn = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(2)
                wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")))
                encontrou = True
                break
            except:
                if "Nenhum registro" in driver.page_source: break
        
        if not encontrou:
            res['status'] = 'nao_encontrado'
            res['mensagem'] = 'Auto não localizado'
            return res

        btn_edit = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_edit)
        
        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))
        for w in driver.window_handles:
            if w != janela_main: driver.switch_to.window(w)
        
        time.sleep(3) 
        
        dados = {}
        try:
            id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
            
            dados['processo'] = esperar_dados(driver, id_proc)
            if not dados['processo']: dados['processo'] = driver.find_element(By.ID, id_proc).get_attribute('value')

            dados['data_infracao'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao").get_attribute('value')
            dados['codigo'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao").get_attribute('value')
            dados['fato'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao").get_attribute('value')

            try:
                xp = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                wait.until(EC.presence_of_element_located((By.XPATH, xp)))
                tab = driver.find_element(By.XPATH, xp)
                trs = tab.find_elements(By.TAG_NAME, "tr")
                if len(trs) > 1:
                    tds = trs[-1].find_elements(By.TAG_NAME, "td")
                    if len(tds) >= 4:
                        dados['data_andamento'] = tds[3].text
                        dados['andamento'] = tds[1].text
                    elif len(tds) >= 2:
                        dados['data_andamento'] = tds[-1].text
                        dados['andamento'] = tds[0].text
            except:
                dados['andamento'] = 'Sem andamentos'
                
            res['status'] = 'sucesso'
            res['dados'] = dados
            res['mensagem'] = 'Sucesso'
        except Exception as e:
            res['mensagem'] = f'Erro leitura: {e}'

        driver.close()
        driver.switch_to.window(janela_main)
        return res

    except Exception as e:
        res['mensagem'] = f'Erro fluxo: {e}'
        if len(driver.window_handles) > 1:
            try: driver.switch_to.window(janela_main)
            except: pass
        return res

# =============================================================================
# INTERFACE GRÁFICA
# =============================================================================
st.title("🚛 Robô ANTT - Final Cloud")

col1, col2 = st.columns(2)
with col1: usuario = st.text_input("Usuário ANTT")
with col2: senha = st.text_input("Senha ANTT", type="password")

arquivo = st.file_uploader("Upload Planilha (.xlsx)", type="xlsx")

# --- BOTÃO DE INÍCIO ---
if st.button("🚀 Iniciar Consulta") and arquivo and usuario:
    try:
        # Carregar planilha
        df = pd.read_excel(arquivo)
        cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
        for c in cols:
            if c not in df.columns: df[c] = ""
        df = df.astype(object).replace('nan', '')

        st.info("Iniciando navegador...")
        driver = get_driver()
        
        if realizar_login_debug(driver, usuario, senha):
            st.success("Login conectado!")
            
            bar = st.progress(0)
            txt = st.empty()
            preview = st.empty()
            
            total = len(df)
            for idx, row in df.iterrows():
                auto = str(row['Auto de Infração']).strip()
                if not auto or auto == 'nan': continue
                
                txt.text(f"Consultando {idx+1}/{total}: {auto}")
                res = processar_auto(driver, auto)
                
                df.at[idx, 'Status Consulta'] = str(res['mensagem'])
                if res['status'] == 'sucesso':
                    d = res['dados']
                    df.at[idx, 'Nº do Processo'] = str(d.get('processo', ''))
                    df.at[idx, 'Data da Infração'] = str(d.get('data_infracao', ''))
                    df.at[idx, 'Código da Infração'] = str(d.get('codigo', ''))
                    df.at[idx, 'Fato Gerador'] = str(d.get('fato', ''))
                    df.at[idx, 'Último Andamento'] = str(d.get('andamento', ''))
                    df.at[idx, 'Data do Último Andamento'] = str(d.get('data_andamento', ''))
                
                bar.progress((idx+1)/total)
                preview.dataframe(df.head(idx+1))
            
            # --- SALVA O RESULTADO NA SESSÃO PARA NÃO PERDER ---
            st.session_state.df_resultado = df
            st.success("Processamento finalizado! O botão de download está logo abaixo.")
            
        else:
            st.warning("Login falhou.")
        
        driver.quit()

    except Exception as e:
        st.error(f"Erro: {e}")

# --- BOTÃO DE DOWNLOAD PERSISTENTE ---
# Fica fora do 'if st.button' para não sumir
if st.session_state.df_resultado is not None:
    st.write("---")
    st.subheader("✅ Download Disponível")
    
    buffer = BytesIO()
    st.session_state.df_resultado.to_excel(buffer, index=False)
    buffer.seek(0)
    
    st.download_button(
        label="📥 Baixar Planilha Atualizada",
        data=buffer,
        file_name="Resultado_Final_ANTT.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
