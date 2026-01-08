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

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Nuvem", page_icon="🚛", layout="wide")

# =============================================================================
# FUNÇÕES CORE (SELENIUM)
# =============================================================================

def get_driver():
    """Configuração ESPECÍFICA para rodar no Streamlit Cloud (Linux/Docker)"""
    chrome_options = Options()
    
    # Flags críticas para o ambiente Cloud
    chrome_options.add_argument("--headless")  # Sem interface gráfica
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detecção
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    try:
        # Tenta usar o webdriver manager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception:
        # Fallback: Se falhar, tenta usar o driver do sistema (instalado pelo packages.txt)
        driver = webdriver.Chrome(options=chrome_options)
        
    return driver

def realizar_login(driver, usuario, senha):
    """Login automatizado"""
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 15)

        # 1. Usuário
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        wait.until(EC.element_to_be_clickable((By.ID, id_user))).send_keys(usuario)

        # 2. OK Inicial
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        btn_ok = driver.find_element(By.ID, id_btn_ok)
        btn_ok.click()
        
        # 3. Senha (se houver)
        try:
            time.sleep(2)
            campo_senha = driver.find_element(By.XPATH, "//input[@type='password']")
            if campo_senha.is_displayed():
                campo_senha.send_keys(senha)
                btn_ok.click()
        except:
            pass
            
        # 4. Confirmação
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        return True
    except Exception as e:
        st.error(f"Erro no Login: {e}")
        return False

def esperar_dados(driver, element_id, timeout=10):
    """Garante que o campo tenha texto antes de ler"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            val = driver.find_element(By.ID, element_id).get_attribute('value')
            if val and val.strip(): return val
            time.sleep(0.5)
        except: pass
    return ""

def processar_auto(driver, auto):
    """Lógica exata do script local que funcionava"""
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
st.title("🚛 Robô ANTT - Nuvem")

usuario = st.text_input("Usuário")
senha = st.text_input("Senha", type="password")
arquivo = st.file_uploader("Upload Planilha (.xlsx)", type="xlsx")

if st.button("Iniciar") and arquivo and usuario:
    try:
        df = pd.read_excel(arquivo)
        
        # Preparação das colunas
        cols = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 'Status Consulta']
        for c in cols:
            if c not in df.columns: df[c] = ""
        df = df.astype(object).replace('nan', '')

        st.info("Iniciando navegador em segundo plano...")
        driver = get_driver()
        
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
            st.error("Falha no login.")
        
        driver.quit()
    except Exception as e:
        st.error(f"Erro Crítico: {e}")
