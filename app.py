import streamlit as st
import pandas as pd
import time
import io
import os
import base64
import gc # Importante para limpeza de memória
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= CONFIGURAÇÃO DA PÁGINA =================
st.set_page_config(
    page_title="Atualizador de Planilha Controle",
    page_icon="🚛",
    layout="wide"
)

# ================= CLASSE DE CONFIGURAÇÃO =================
class ConfigWeb:
    def __init__(self):
        self.url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        self.url_consulta = 'https://appweb1.antt.gov.br/spm/Site/DefesaCTB/ConsultaProcessoSituacao.aspx'
        self.col_auto = 'Auto de Infração'
        self.col_processo = 'Nº do Processo'
        self.col_status = 'Status Consulta'
        self.col_andamento = 'Último Andamento'
        self.timeout_padrao = 25
        self.sleep_pos_clique = 5
        # === NOVO: Configuração de Lote ===
        self.reiniciar_a_cada = 30 # A cada 30 consultas, fecha tudo e reabre para não travar

# ================= DOWNLOAD AUTOMÁTICO =================
def download_automatico(df):
    try:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        val = buffer.getvalue()
        b64 = base64.b64encode(val).decode()
        
        md = f"""
        <script>
            var link = document.createElement('a');
            link.href = 'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}';
            link.download = 'Planilha_ANTT_Parcial.xlsx';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        </script>
        """
        st.components.v1.html(md, height=0)
        return True
    except Exception: return False

# ================= DRIVER OTIMIZADO =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage") # Essencial para Docker/Cloud
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--window-size=1920,1080")
    # Limpa cache de disco para economizar espaço
    chrome_options.add_argument("--disk-cache-size=1") 
    chrome_options.add_argument("--media-cache-size=1")
    
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

# ================= LOGIN =================
def realizar_login(driver, usuario, senha, config):
    wait = WebDriverWait(driver, config.timeout_padrao)
    try:
        if "ConsultaProcessoSituacao" not in driver.current_url:
            driver.get(config.url_login)
            time.sleep(4)
        
        if "sca/Site/Login" in driver.current_url:
            try:
                driver.find_element(By.XPATH, "//input[contains(@name, 'Usuario') or contains(@id, 'User')]").send_keys(usuario)
                driver.find_element(By.XPATH, "//input[@type='password']").send_keys(senha)
                driver.find_element(By.XPATH, "//input[@type='submit'] | //a[contains(@id, 'Login')]").click()
                time.sleep(config.sleep_pos_clique)
            except: pass

        if "sso.acesso.gov.br" in driver.current_url:
            try:
                wait.until(EC.presence_of_element_located((By.ID, "accountId"))).send_keys(usuario)
                driver.find_element(By.XPATH, "//button[contains(text(), 'Continuar')]").click()
                time.sleep(4)
                wait.until(EC.presence_of_element_located((By.ID, "password"))).send_keys(senha)
                driver.find_element(By.ID, "submit-button").click()
                time.sleep(6) 
            except: pass

        if "ConsultaProcessoSituacao" in driver.current_url: return True
        
        driver.get(config.url_consulta)
        time.sleep(4)
        if "ConsultaProcessoSituacao" in driver.current_url: return True
             
        return False
    except Exception: return False

# ================= GARANTIR SESSÃO =================
def garantir_sessao(driver, usuario, senha, config):
    try:
        # Verifica se caiu na tela de login ou erro
        url = driver.current_url.lower()
        if "consultaprocessosituacao" not in url or "login" in url:
            return realizar_login(driver, usuario, senha, config)
        return True
    except: return False

# ================= CONSULTA =================
def consultar_auto(driver, auto, config):
    resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, config.timeout_padrao)
    
    try:
        if "ConsultaProcessoSituacao" not in driver.current_url:
             driver.get(config.url_consulta)
             time.sleep(2)
        
        try:
            campo = wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
            campo.clear()
            campo.send_keys(auto)
            
            btn = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(config.sleep_pos_clique)
            
        except: return {'status': 'erro_conexao', 'dados': {}, 'mensagem': 'Timeout pesquisa'}
        
        src = driver.page_source.lower()
        if "nenhum registro" in src or "não encontrado" in src:
            resultado['status'] = 'nao_encontrado'
            resultado['mensagem'] = 'Auto não localizado'
            return resultado

        sucesso = False
        for _ in range(3): # 3 Tentativas de abrir detalhe
            try:
                btn_edit = driver.find_element(By.XPATH, "//input[contains(@id, 'btnEditar')] | //a[contains(@title, 'Editar')]")
                driver.execute_script("arguments[0].click();", btn_edit)
                time.sleep(config.sleep_pos_clique)
                
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'txbProcesso')]")))
                    sucesso = True
                    break
                time.sleep(2)
            except: time.sleep(2)
        
        if sucesso:
            dados = {}
            try:
                dados['processo'] = driver.find_element(By.XPATH, "//*[contains(@id, 'txbProcesso')]").get_attribute('value')
                try:
                    trs = driver.find_elements(By.XPATH, "//table[contains(@class, 'tabela-conteudo')]//tr")
                    if len(trs) > 1: dados['ultimo_andamento'] = trs[-1].find_elements(By.TAG_NAME, "td")[1].text
                    else: dados['ultimo_andamento'] = "Sem histórico"
                except: dados['ultimo_andamento'] = "-"
            except: dados['processo'] = "Erro leitura"

            resultado['dados'] = dados
            resultado['status'] = 'sucesso'
            resultado['mensagem'] = 'Sucesso'
            
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        else:
            resultado['status'] = 'erro_interacao'
            resultado['mensagem'] = 'Detalhe não abriu'

    except Exception as e: resultado['mensagem'] = f"Erro: {str(e)[:15]}"
        
    return resultado

# ================= INTERFACE =================
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists("logo.png"): st.image("logo.png", width=100)
    else: st.image("https://upload.wikimedia.org/wikipedia/commons/5/52/Logo_ANTT.svg", width=100)

with col_title:
    st.markdown("<h1 style='margin-top: -10px;'>Atualizador de Planilha Controle</h1>", unsafe_allow_html=True)
    st.caption("Sistema Otimizado com Gestão de Memória e Auto-Recuperação")

st.divider()

if 'df_final' not in st.session_state: st.session_state.df_final = None
if 'logs' not in st.session_state: st.session_state.logs = []

with st.sidebar:
    st.header("🔐 Credenciais")
    cpf_input = st.text_input("Usuário/CPF")
    senha_input = st.text_input("Senha", type="password")
    st.divider()
    pular_feitos = st.checkbox("Pular já concluídos", value=True)
    remover_duplicados = st.checkbox("Remover duplicados", value=True)
    limitador = st.number_input("Limite (0=Tudo)", min_value=0, value=0)

uploaded_file = st.file_uploader("📂 Planilha (.xlsx)", type=['xlsx'])

if uploaded_file and st.button("▶️ Iniciar"):
    if not cpf_input or not senha_input:
        st.error("⚠️ Preencha o Login!")
    else:
        config = ConfigWeb()
        df = pd.read_excel(uploaded_file)
        
        # Limpeza Inicial
        for col in [config.col_processo, config.col_status, config.col_andamento, config.col_auto]:
             if col in df.columns: df[col] = df[col].astype(str).replace('nan', '')
             else: df[col] = ""

        if remover_duplicados: df = df.drop_duplicates(subset=[config.col_auto], keep='first')
        if limitador > 0: df = df.head(limitador)

        # UI Components
        status_box = st.status("Inicializando...", expanded=True)
        progress_bar = st.progress(0)
        log_placeholder = st.empty() # Área para logs
        
        driver = get_driver()
        cache = {}
        
        try:
            status_box.write("🔐 Logando...")
            if not realizar_login(driver, cpf_input, senha_input, config):
                st.error("❌ Falha Login")
                status_box.update(label="Erro Login", state="error")
            else:
                status_box.write("✅ Logado! Iniciando...")
                total = len(df)
                df = df.reset_index(drop=True)
                
                contador_lote = 0 # Contador para reiniciar navegador

                for index, row in df.iterrows():
                    # === GESTÃO DE MEMÓRIA (O SEGREDO DO SUCESSO) ===
                    contador_lote += 1
                    if contador_lote >= config.reiniciar_a_cada:
                        status_box.write("🧹 Limpando memória RAM (Reiniciando navegador)...")
                        driver.quit()
                        gc.collect() # Força limpeza do Python
                        time.sleep(2)
                        driver = get_driver() # Abre novo limpo
                        realizar_login(driver, cpf_input, senha_input, config)
                        contador_lote = 0 # Zera contador
                        status_box.write("♻️ Navegador reiniciado. Continuando...")

                    auto = str(row[config.col_auto]).strip()
                    status_atual = str(row[config.col_status])
                    
                    # Lógica de Pular
                    if pular_feitos and ("Sucesso" in status_atual or "Processo" in status_atual):
                        msg = f"⏭️ {index+1}/{total}: {auto} (Pulado)"
                        st.session_state.logs.insert(0, msg)
                        log_placeholder.text("\n".join(st.session_state.logs[:10]))
                        progress_bar.progress((index + 1) / total)
                        continue

                    # Lógica de Consulta
                    if auto in cache:
                        res = cache[auto]
                        st.session_state.logs.insert(0, f"♻️ {index+1}/{total}: {auto} (Cache)")
                    else:
                        status_box.update(label=f"🔄 [{index+1}/{total}] Consultando: {auto}")
                        
                        # Verifica sessão antes
                        if not garantir_sessao(driver, cpf_input, senha_input, config):
                            st.session_state.logs.insert(0, f"⛔ {index+1}/{total}: Sessão caiu")
                            continue
                            
                        res = consultar_auto(driver, auto, config)
                        cache[auto] = res
                    
                    # Salva Resultado
                    df.at[index, config.col_status] = res['mensagem']
                    if res['status'] == 'sucesso':
                        df.at[index, config.col_processo] = res['dados'].get('processo', '')
                        df.at[index, config.col_andamento] = res['dados'].get('ultimo_andamento', '')
                        icon = "✅"
                    elif res['status'] == 'nao_encontrado': icon = "⚠️"
                    else: icon = "❌"
                    
                    # Atualiza Logs
                    st.session_state.logs.insert(0, f"{icon} {index+1}/{total}: {auto} - {res['mensagem']}")
                    log_placeholder.text("\n".join(st.session_state.logs[:10]))
                    progress_bar.progress((index + 1) / total)
                    
                    # SALVA ESTADO PARCIAL A CADA LINHA (Para não perder tudo se cair)
                    st.session_state.df_final = df.copy()

                status_box.update(label="Concluído!", state="complete")
                st.success("Finalizado!")
                download_automatico(df)

        except Exception as e:
            st.error(f"Erro Crítico: {e}")
        finally:
            if driver: driver.quit()

# ================= DOWNLOAD MANUAL =================
if st.session_state.df_final is not None:
    st.divider()
    st.info("Backup dos dados processados disponível abaixo:")
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        st.session_state.df_final.to_excel(writer, index=False)
    
    st.download_button(
        label="📥 Baixar Planilha (Backup)",
        data=buffer.getvalue(),
        file_name="Planilha_ANTT_Backup.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
