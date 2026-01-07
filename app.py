import streamlit as st
import pandas as pd
import time
import io
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= CONFIGURAÇÃO DA PÁGINA =================
st.set_page_config(page_title="Robô ANTT - Final", layout="wide")

# ================= CONFIGURAÇÃO =================
class ConfigWeb:
    def __init__(self):
        self.url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        self.url_consulta = 'https://appweb1.antt.gov.br/spm/Site/DefesaCTB/ConsultaProcessoSituacao.aspx'
        self.col_auto = 'Auto de Infração'
        self.col_processo = 'Nº do Processo'
        self.col_status = 'Status Consulta'
        self.col_andamento = 'Último Andamento'

# ================= DRIVER =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

# ================= LOGIN =================
def realizar_login(driver, usuario, senha, config):
    wait = WebDriverWait(driver, 15)
    try:
        driver.get(config.url_login)
        time.sleep(3)
        
        # 1. Login Antigo (SCA)
        if "sca/Site/Login" in driver.current_url:
            try:
                driver.find_element(By.XPATH, "//input[contains(@name, 'Usuario') or contains(@id, 'User')]").send_keys(usuario)
                driver.find_element(By.XPATH, "//input[@type='password']").send_keys(senha)
                driver.find_element(By.XPATH, "//input[@type='submit'] | //a[contains(@id, 'Login')]").click()
                time.sleep(5)
            except: pass

        # 2. Login Gov.br
        if "sso.acesso.gov.br" in driver.current_url:
            try:
                wait.until(EC.presence_of_element_located((By.ID, "accountId"))).send_keys(usuario)
                driver.find_element(By.XPATH, "//button[contains(text(), 'Continuar')]").click()
                time.sleep(3)
                wait.until(EC.presence_of_element_located((By.ID, "password"))).send_keys(senha)
                driver.find_element(By.ID, "submit-button").click()
                time.sleep(5)
            except: pass

        if "ConsultaProcessoSituacao" in driver.current_url: return True, "Login OK"
        
        driver.get(config.url_consulta)
        time.sleep(3)
        if "ConsultaProcessoSituacao" in driver.current_url: return True, "Login OK (Redirecionado)"
             
        return False, "Falha no Login (Verifique Usuário/Senha)"
    except Exception as e:
        return False, str(e)

# ================= CONSULTA =================
def consultar_auto(driver, auto, config):
    resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 8)
    
    try:
        if "ConsultaProcessoSituacao" not in driver.current_url:
             driver.get(config.url_consulta)
        
        try:
            campo = wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
            campo.clear()
            campo.send_keys(auto)
            driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar").click()
            time.sleep(2)
        except:
             # Tenta recuperar se a sessão caiu
             driver.refresh()
             return {'status': 'erro', 'dados': {}, 'mensagem': 'Erro conexão (tentando prox)'}
        
        src = driver.page_source.lower()
        if "nenhum registro" in src or "não encontrado" in src:
            resultado['status'] = 'nao_encontrado'
            resultado['mensagem'] = 'Auto não localizado'
            return resultado

        try:
            driver.find_element(By.XPATH, "//input[contains(@id, 'btnEditar')] | //a[contains(@title, 'Editar')]").click()
            time.sleep(2)
            
            janela_principal = driver.window_handles[0]
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
            
            dados = {}
            try:
                dados['processo'] = driver.find_element(By.XPATH, "//*[contains(@id, 'txbProcesso')]").get_attribute('value')
                try:
                    linhas = driver.find_elements(By.XPATH, "//table[contains(@class, 'tabela-conteudo')]//tr")
                    if len(linhas) > 1:
                        dados['ultimo_andamento'] = linhas[-1].find_elements(By.TAG_NAME, "td")[1].text
                    else:
                        dados['ultimo_andamento'] = "Sem histórico"
                except:
                    dados['ultimo_andamento'] = "-"
            except:
                dados['processo'] = "Erro leitura"

            resultado['dados'] = dados
            resultado['status'] = 'sucesso'
            resultado['mensagem'] = 'Sucesso'
            
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(janela_principal)
                
        except:
            resultado['status'] = 'erro_interacao'
            resultado['mensagem'] = 'Falha ao abrir detalhe'

    except Exception as e:
        resultado['mensagem'] = f"Erro: {str(e)[:30]}"
        
    return resultado

# ================= INTERFACE =================
st.title("🕵️ Robô ANTT - Versão Final")

with st.sidebar:
    st.header("🔐 Acesso")
    cpf_input = st.text_input("Usuário/CPF")
    senha_input = st.text_input("Senha", type="password")
    
    st.divider()
    st.header("⚡ Filtros")
    pular_feitos = st.checkbox("⏩ Pular já realizados ('Sucesso')", value=True)
    remover_duplicados = st.checkbox("🧹 Remover autos duplicados da lista", value=True)
    limitador = st.number_input("Limite de linhas (0 = Tudo)", min_value=0, value=0)

uploaded_file = st.file_uploader("Planilha (entrada.xlsx)", type=['xlsx'])

if uploaded_file and st.button("🚀 Iniciar"):
    if not cpf_input or not senha_input:
        st.error("Preencha o login!")
    else:
        config = ConfigWeb()
        df = pd.read_excel(uploaded_file)
        
        # Preparação das colunas
        for col in [config.col_processo, config.col_status, config.col_andamento, config.col_auto]:
             if col in df.columns: df[col] = df[col].astype(str).replace('nan', '')
             else: df[col] = ""

        # === LIMPEZA DE DUPLICADOS (NOVO) ===
        if remover_duplicados:
            antes = len(df)
            # Remove duplicatas baseadas no Auto, mantendo a primeira ocorrência
            df = df.drop_duplicates(subset=[config.col_auto], keep='first')
            depois = len(df)
            if antes > depois:
                st.toast(f"🧹 Removidos {antes-depois} autos repetidos da planilha!")

        if limitador > 0:
            df = df.head(limitador)
            st.warning(f"Modo Teste: {limitador} linhas")

        # UI CONFIG
        status_box = st.status("Iniciando...", expanded=True)
        progress_bar = st.progress(0)
        
        # === CORREÇÃO DO LOG VISUAL (O SEGREDO ESTÁ AQUI) ===
        with st.expander("Logs (Últimos 10)", expanded=True):
            log_container = st.empty() # Placeholder que limpa o texto anterior
            
        logs = []
        cache_consultas = {} 

        driver = get_driver()
        
        try:
            sucesso, msg = realizar_login(driver, cpf_input, senha_input, config)
            if not sucesso:
                st.error(msg)
                status_box.update(label="Erro Login", state="error")
            else:
                status_box.write("Login OK. Processando...")
                total = len(df)
                
                # Reseta o index após remover duplicatas para a barra de progresso funcionar
                df = df.reset_index(drop=True)

                for index, row in df.iterrows():
                    auto = str(row[config.col_auto]).strip()
                    status_atual = str(row[config.col_status])
                    
                    # 1. Pular Feitos
                    if pular_feitos and ("Sucesso" in status_atual or "Processo" in status_atual):
                        logs.insert(0, f"⏭️ [{index+1}] {auto}: Já pronto")
                        log_container.text("\n".join(logs[:10])) # Usa .text no container vazio
                        progress_bar.progress((index + 1) / total)
                        continue

                    # 2. Cache
                    if auto in cache_consultas:
                        res = cache_consultas[auto]
                        logs.insert(0, f"♻️ [{index+1}] {auto}: Cache")
                    else:
                        # 3. Consulta Real
                        status_box.update(label=f"Consultando {index+1}/{total}: {auto}")
                        res = consultar_auto(driver, auto, config)
                        cache_consultas[auto] = res
                    
                    # Salvar dados
                    df.at[index, config.col_status] = res['mensagem']
                    if res['status'] == 'sucesso':
                        df.at[index, config.col_processo] = res['dados'].get('processo', '')
                        df.at[index, config.col_andamento] = res['dados'].get('ultimo_andamento', '')
                        icon = "✅"
                    elif res['status'] == 'nao_encontrado': icon = "⚠️"
                    else: icon = "❌"
                    
                    # Atualiza Log Visual (Agora sem duplicar!)
                    logs.insert(0, f"{icon} [{index+1}] {auto}: {res['mensagem']}")
                    log_container.text("\n".join(logs[:10])) # Substitui o texto anterior
                    
                    progress_bar.progress((index + 1) / total)

                status_box.update(label="Concluído!", state="complete")
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                
                st.success("Tudo pronto!")
                st.download_button("📥 Baixar Planilha", buffer.getvalue(), "antt_final.xlsx")

        except Exception as e:
            st.error(f"Erro: {e}")
        finally:
            driver.quit()
