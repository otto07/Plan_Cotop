import streamlit as st
import pandas as pd
import time
import io
import os
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= CONFIGURAÇÃO DA PÁGINA =================
st.set_page_config(page_title="Robô ANTT - Ultra Resiliente", layout="wide")

# ================= CLASSE DE CONFIGURAÇÃO =================
class ConfigWeb:
    def __init__(self):
        self.url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        self.url_consulta = 'https://appweb1.antt.gov.br/spm/Site/DefesaCTB/ConsultaProcessoSituacao.aspx'
        self.col_auto = 'Auto de Infração'
        self.col_processo = 'Nº do Processo'
        self.col_status = 'Status Consulta'
        self.col_andamento = 'Último Andamento'
        # Aumentei os tempos de tolerância
        self.timeout_padrao = 30 
        self.sleep_pos_clique = 6 # Tempo fixo para esperar o site "pensar"

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

# ================= LOGIN ROBUSTO =================
def realizar_login(driver, usuario, senha, config):
    wait = WebDriverWait(driver, config.timeout_padrao)
    try:
        # Só navega se já não estiver na página certa (economiza tempo)
        if "ConsultaProcessoSituacao" not in driver.current_url:
            driver.get(config.url_login)
            time.sleep(5)
        
        # 1. Login Antigo (SCA)
        if "sca/Site/Login" in driver.current_url:
            try:
                driver.find_element(By.XPATH, "//input[contains(@name, 'Usuario') or contains(@id, 'User')]").send_keys(usuario)
                driver.find_element(By.XPATH, "//input[@type='password']").send_keys(senha)
                driver.find_element(By.XPATH, "//input[@type='submit'] | //a[contains(@id, 'Login')]").click()
                time.sleep(config.sleep_pos_clique)
            except: pass

        # 2. Login Gov.br
        if "sso.acesso.gov.br" in driver.current_url:
            try:
                wait.until(EC.presence_of_element_located((By.ID, "accountId"))).send_keys(usuario)
                driver.find_element(By.XPATH, "//button[contains(text(), 'Continuar')]").click()
                time.sleep(5)
                wait.until(EC.presence_of_element_located((By.ID, "password"))).send_keys(senha)
                driver.find_element(By.ID, "submit-button").click()
                time.sleep(8) # Gov.br é lento
            except: pass

        # Validação Final
        if "ConsultaProcessoSituacao" in driver.current_url: return True
        
        # Tenta forçar URL final
        driver.get(config.url_consulta)
        time.sleep(5)
        if "ConsultaProcessoSituacao" in driver.current_url: return True
             
        return False
    except Exception:
        return False

# ================= GUARDIÃO DE SESSÃO (NOVO) =================
def garantir_sessao(driver, usuario, senha, config):
    """Verifica se caiu e reloga automaticamente"""
    try:
        # Se não estiver na URL de consulta OU se tiver redirecionado para Login
        if "ConsultaProcessoSituacao" not in driver.current_url or "Login" in driver.current_url:
            # Tenta relogar silenciosamente
            return realizar_login(driver, usuario, senha, config)
        return True
    except:
        return False

# ================= CONSULTA PACIENTE =================
def consultar_auto(driver, auto, config):
    resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, config.timeout_padrao)
    
    try:
        # Verifica URL
        if "ConsultaProcessoSituacao" not in driver.current_url:
             driver.get(config.url_consulta)
             time.sleep(3)
        
        # 1. BUSCA (COM ESPERA LONGA)
        try:
            campo = wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
            campo.clear()
            campo.send_keys(auto)
            
            # Clica em Pesquisar
            btn_pesquisar = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
            driver.execute_script("arguments[0].click();", btn_pesquisar)
            
            # === ESPERA OBRIGATÓRIA PÓS-PESQUISA (LENTIDÃO DO SITE) ===
            time.sleep(config.sleep_pos_clique)
            
        except:
             return {'status': 'erro_conexao', 'dados': {}, 'mensagem': 'Site não respondeu à pesquisa'}
        
        # Verifica se achou ou se deu "Não encontrado"
        src = driver.page_source.lower()
        if "nenhum registro" in src or "não encontrado" in src:
            resultado['status'] = 'nao_encontrado'
            resultado['mensagem'] = 'Auto não localizado'
            return resultado

        # 2. ABRIR DETALHES (COM INSISTÊNCIA)
        sucesso_clique = False
        
        # Tenta 3 vezes clicar no editar, caso o site esteja "pensando"
        for i in range(3):
            try:
                btn = driver.find_element(By.XPATH, "//input[contains(@id, 'btnEditar')] | //a[contains(@title, 'Editar')]")
                driver.execute_script("arguments[0].click();", btn)
                
                # === ESPERA OBRIGATÓRIA PARA ABRIR O POPUP ===
                time.sleep(config.sleep_pos_clique + 2) 
                
                # Verifica janelas
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    
                    # Espera elemento do processo carregar na nova janela
                    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'txbProcesso')]")))
                    
                    sucesso_clique = True
                    break
                else:
                    time.sleep(3) # Tenta de novo
            except:
                time.sleep(3)
        
        if sucesso_clique:
            dados = {}
            try:
                dados['processo'] = driver.find_element(By.XPATH, "//*[contains(@id, 'txbProcesso')]").get_attribute('value')
                try:
                    # Pega andamento com espera explícita
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
            
            # Fecha e volta
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        else:
            resultado['status'] = 'erro_interacao'
            resultado['mensagem'] = 'Site lento: Detalhe não abriu'

    except Exception as e:
        resultado['mensagem'] = f"Erro técnico: {str(e)[:20]}"
        
    return resultado

# ================= INTERFACE =================
st.title("🐢 Robô ANTT - Modo Paciente")

with st.sidebar:
    st.header("🔐 Acesso")
    cpf_input = st.text_input("Usuário/CPF")
    senha_input = st.text_input("Senha", type="password")
    
    st.divider()
    st.header("⚡ Filtros")
    pular_feitos = st.checkbox("⏩ Pular já realizados", value=True)
    remover_duplicados = st.checkbox("🧹 Remover duplicados", value=True)
    limitador = st.number_input("Limite (0 = Tudo)", min_value=0, value=0)

uploaded_file = st.file_uploader("Planilha (entrada.xlsx)", type=['xlsx'])

if uploaded_file and st.button("🚀 Iniciar"):
    if not cpf_input or not senha_input:
        st.error("Preencha o login!")
    else:
        config = ConfigWeb()
        df = pd.read_excel(uploaded_file)
        
        for col in [config.col_processo, config.col_status, config.col_andamento, config.col_auto]:
             if col in df.columns: df[col] = df[col].astype(str).replace('nan', '')
             else: df[col] = ""

        if remover_duplicados:
            df = df.drop_duplicates(subset=[config.col_auto], keep='first')
        if limitador > 0:
            df = df.head(limitador)

        status_box = st.status("Iniciando navegador...", expanded=True)
        progress_bar = st.progress(0)
        
        with st.expander("Logs em Tempo Real", expanded=True):
            log_container = st.empty()
            
        logs = []
        cache_consultas = {} 

        driver = get_driver()
        
        try:
            status_box.write("🔐 Realizando login inicial...")
            if not realizar_login(driver, cpf_input, senha_input, config):
                st.error("Falha no login inicial. Verifique usuário/senha.")
                status_box.update(label="Erro Login", state="error")
            else:
                status_box.write("Login OK. Iniciando modo paciente...")
                total = len(df)
                df = df.reset_index(drop=True)

                for index, row in df.iterrows():
                    auto = str(row[config.col_auto]).strip()
                    status_atual = str(row[config.col_status])
                    
                    # Filtros iniciais
                    if pular_feitos and ("Sucesso" in status_atual or "Processo" in status_atual):
                        logs.insert(0, f"⏭️ [{index+1}] {auto}: Pronto")
                        log_container.text("\n".join(logs[:15]))
                        progress_bar.progress((index + 1) / total)
                        continue

                    if auto in cache_consultas:
                        res = cache_consultas[auto]
                        logs.insert(0, f"♻️ [{index+1}] {auto}: Cache")
                    else:
                        # === O PULO DO GATO: VERIFICA SESSÃO ANTES DE CONSULTAR ===
                        status_box.update(label=f"[{index+1}/{total}] {auto} (Verificando sessão...)")
                        sessao_ok = garantir_sessao(driver, cpf_input, senha_input, config)
                        
                        if not sessao_ok:
                            logs.insert(0, f"⛔ [{index+1}] {auto}: Sessão caiu e não voltou")
                            # Tenta mais uma vez na próxima volta
                            continue 
                        
                        status_box.update(label=f"[{index+1}/{total}] Consultando {auto}...")
                        res = consultar_auto(driver, auto, config)
                        cache_consultas[auto] = res
                    
                    # Salva
                    df.at[index, config.col_status] = res['mensagem']
                    if res['status'] == 'sucesso':
                        df.at[index, config.col_processo] = res['dados'].get('processo', '')
                        df.at[index, config.col_andamento] = res['dados'].get('ultimo_andamento', '')
                        icon = "✅"
                    elif res['status'] == 'nao_encontrado': icon = "⚠️"
                    elif res['status'] == 'erro_conexao': icon = "🔌"
                    else: icon = "❌"
                    
                    logs.insert(0, f"{icon} [{index+1}] {auto}: {res['mensagem']}")
                    log_container.text("\n".join(logs[:15]))
                    progress_bar.progress((index + 1) / total)

                status_box.update(label="Processamento Concluído!", state="complete")
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                
                st.success("Tudo pronto! O robô venceu a lentidão do site.")
                st.download_button("📥 Baixar Planilha", buffer.getvalue(), "antt_final_paciente.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")
        finally:
            driver.quit()
