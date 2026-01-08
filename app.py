import streamlit as st
import pandas as pd
import time
import os
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys  # <--- IMPORTANTE
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Cloud Pro", page_icon="🚛", layout="wide")

# =============================================================================
# SETUP DO DRIVER (LINUX/CLOUD)
# =============================================================================

def get_driver():
    """Configuração para rodar no Streamlit Cloud usando binários do sistema"""
    chrome_options = Options()
    
    # Aponta para os binários instalados pelo packages.txt
    chrome_options.binary_location = "/usr/bin/chromium"
    
    # Flags vitais para ambiente Container/Linux
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detecção
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        # Usa o driver do sistema
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        st.error(f"Erro ao iniciar o driver: {e}")
        st.stop()

# =============================================================================
# FUNÇÕES DE NEGÓCIO
# =============================================================================

def realizar_login_agressivo(driver, usuario, senha):
    """
    Login com injeção de JS para garantir que a senha seja lida
    """
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 20)

        # 1. Inserir Usuário
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        campo_user.clear()
        campo_user.send_keys(usuario)

        # 2. Clicar OK (Primeira etapa)
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        btn_ok = driver.find_element(By.ID, id_btn_ok)
        btn_ok.click()
        
        # 3. Tratamento da Senha (AQUI ESTÁ A CORREÇÃO)
        try:
            # Espera o campo de senha aparecer (pode demorar pelo postback)
            xpath_senha = "//input[@type='password']"
            wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
            
            # Pausa técnica para o ASP.NET carregar os scripts da página
            time.sleep(2)
            
            campo_senha = driver.find_element(By.XPATH, xpath_senha)
            
            # A) Digitação normal
            campo_senha.click()
            campo_senha.clear()
            campo_senha.send_keys(senha)
            
            # B) FORÇA BRUTA: Injeta o valor via JavaScript (caso o send_keys falhe no headless)
            driver.execute_script(f"arguments[0].value = '{senha}';", campo_senha)
            
            # C) Dispara eventos para acordar o validador do site
            driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", campo_senha)
            driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", campo_senha)
            
            time.sleep(0.5)
            
            # D) Envia ENTER direto no campo (evita clicar em botão que pode estar travado)
            campo_senha.send_keys(Keys.RETURN)
            
        except Exception as e:
            # Se cair aqui, pode ser que o login foi direto sem senha ou erro de timeout
            pass
            
        # 4. Confirmação de Sucesso
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        return True

    except Exception as e:
        st.error(f"Falha no Login: {e}")
        # Debug visual em caso de erro
        try:
            st.image(driver.get_screenshot_as_png(), caption="Erro no Login")
        except:
            pass
        return False

def esperar_dados(driver, element_id, timeout=10):
    """Espera o dado aparecer no campo"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            val = driver.find_element(By.ID, element_id).get_attribute('value')
            if val and val.strip(): return val
            time.sleep(0.5)
        except: pass
    return ""

def processar_auto(driver, auto):
    """Lógica de extração mantendo o que funcionava"""
    res = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 20)
    janela_main = driver.current_window_handle
    
    try:
        # 1. Buscar
        campo = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        campo.clear()
        campo.send_keys(auto)
        
        # 2. Pesquisar (Retry + JS Click)
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
        
        time.sleep(3) # Pausa técnica
        
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

            # Tabela (Coluna 4 -> Index 3)
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

usuario = st.text_input("Usuário ANTT")
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

        st.info("Iniciando navegador...")
        
        driver = get_driver()
        
        if realizar_login_agressivo(driver, usuario, senha):
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
            st.warning("Não foi possível logar. O site não aceitou a senha.")
        
        driver.quit()
    except Exception as e:
        st.error(f"Erro Crítico: {e}")
