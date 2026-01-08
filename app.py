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

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Cloud Pro", page_icon="🚛", layout="wide")

# =============================================================================
# FUNÇÕES CORE (SELENIUM BLINDADO PARA LINUX)
# =============================================================================

def get_driver():
    """Configuração para rodar EXCLUSIVAMENTE no Streamlit Cloud (Linux)"""
    chrome_options = Options()
    
    # --- CAMINHO DO BINÁRIO DO CHROME (INSTALADO VIA PACKAGES.TXT) ---
    chrome_options.binary_location = "/usr/bin/chromium"
    
    # --- ARGUMENTOS VITAIS PARA DOCKER/LINUX ---
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage") # Evita crash de memória
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # --- ANTI-BLOQUEIO ---
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")

    # --- CAMINHO DO DRIVER (INSTALADO VIA PACKAGES.TXT) ---
    try:
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        # Fallback para tentativa local (caso você rode no Windows para testar)
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except:
            st.error(f"Erro fatal ao iniciar driver: {e}")
            raise e

def realizar_login(driver, usuario, senha):
    """Login com tratamento de erro visual (Screenshot)"""
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 20)

        # 1. Usuário
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        campo_user.clear()
        campo_user.send_keys(usuario)

        # 2. Botão OK
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        btn_ok = driver.find_element(By.ID, id_btn_ok)
        btn_ok.click()
        
        # 3. Senha (se houver)
        try:
            time.sleep(3)
            # Verifica se apareceu campo de senha
            campo_senha = driver.find_element(By.XPATH, "//input[@type='password']")
            if campo_senha.is_displayed():
                campo_senha.clear()
                campo_senha.send_keys(senha)
                btn_ok.click()
        except:
            pass
            
        # 4. Confirmação
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        return True

    except Exception as e:
        st.error(f"Erro no Login: {e}")
        # Tira print da tela para debug
        try:
            st.image(driver.get_screenshot_as_png(), caption="Tela do Erro no Login")
        except:
            pass
        return False

def esperar_dados(driver, element_id, timeout=10):
    """Espera dados aparecerem no campo"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            val = driver.find_element(By.ID, element_id).get_attribute('value')
            if val and val.strip(): return val
            time.sleep(0.5)
        except: pass
    return ""

def processar_auto(driver, auto):
    """Lógica principal de extração"""
    res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 20)
    janela_main = driver.current_window_handle
    
    try:
        # 1. Buscar
        campo = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        campo.clear()
        campo.send_keys(auto)
        
        # 2. Pesquisar (Retry)
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

        # 3. Abrir Popup
        btn_edit = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_edit)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_edit)
        
        # 4. Trocar Janela
        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))
        for w in driver.window_handles:
            if w != janela_main: driver.switch_to.window(w)
        
        time.sleep(3) # Pausa técnica vital
        
        # 5. Extrair
        dados = {}
        try:
            id_proc = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            wait.until(EC.visibility_of_element_located((By.ID, id_proc)))
            
            dados['processo'] = esperar_dados(driver, id_proc)
            if not dados['processo']: dados['processo'] = driver.find_element(By.ID, id_proc).get_attribute('value')

            dados['data_infracao'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao").get_attribute('value')
            dados['codigo'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao").get_attribute('value')
            dados['fato'] = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao").get_attribute('value')

            # Tabela
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
# INTERFACE
# =============================================================================
st.title("🚛 Robô ANTT - Nuvem Pro")

tab1, tab2 = st.tabs(["🔍 Consulta Automática", "📊 Comparação de Planilhas"])

# --- ABA 1 ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        usuario = st.text_input("Usuário ANTT")
    with col2:
        senha = st.text_input("Senha ANTT", type="password")

    arquivo = st.file_uploader("Upload Planilha (.xlsx)", type="xlsx")

    if st.button("Iniciar") and arquivo and usuario:
        try:
            df = pd.read_excel(arquivo)
            cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                    'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
            for c in cols:
                if c not in df.columns: df[c] = ""
            df = df.astype(object).replace('nan', '')

            st.info("Iniciando navegador Linux...")
            
            # --- TENTATIVA DE INICIALIZAÇÃO SEGURA ---
            try:
                driver = get_driver()
            except Exception as e:
                st.error("Erro ao iniciar Chromium. Verifique se 'packages.txt' está no GitHub.")
                st.stop()

            if realizar_login(driver, usuario, senha):
                st.success("Login efetuado!")
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
                
                output = BytesIO()
                df.to_excel(output, index=False)
                output.seek(0)
                st.download_button("📥 Baixar Resultado", data=output, file_name="Resultado_ANTT.xlsx")
                
            else:
                st.warning("Não foi possível logar. Veja o print do erro acima.")
            
            driver.quit()
        except Exception as e:
            st.error(f"Erro Crítico: {e}")

# --- ABA 2 ---
with tab2:
    col_a, col_b = st.columns(2)
    with col_a: f_antigo = st.file_uploader("Planilha Antiga", type=["xlsx"], key="ant")
    with col_b: f_novo = st.file_uploader("Planilha Nova", type=["xlsx"], key="nov")

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
