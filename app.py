import streamlit as st
import pandas as pd
import time
import io
import os
import base64
import gc
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= CONFIGURAÇÃO DA PÁGINA =================
st.set_page_config(
    page_title="Sistema Integrado ANTT",
    page_icon="🚛",
    layout="wide"
)

# ================= FUNÇÕES AUXILIARES =================
def download_automatico(df, nome_arquivo):
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
            link.download = '{nome_arquivo}';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        </script>
        """
        st.components.v1.html(md, height=0)
        return True
    except Exception: return False

def normalizar_auto(valor):
    """Limpa e padroniza o número do auto"""
    return str(valor).strip().upper().replace(' ', '')

# ================= CLASSE DO ROBÔ =================
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
        self.reiniciar_a_cada = 30

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disk-cache-size=1") 
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    return webdriver.Chrome(options=chrome_options)

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
        for _ in range(3):
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

# ================= INTERFACE PRINCIPAL =================
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists("logo.png"): st.image("logo.png", width=100)
    else: st.image("https://upload.wikimedia.org/wikipedia/commons/5/52/Logo_ANTT.svg", width=100)

with col_title:
    st.markdown("<h1 style='margin-top: -10px;'>Sistema Integrado ANTT</h1>", unsafe_allow_html=True)
    st.caption("Automação de Consultas e Gestão de Planilhas")

# ABAS DO SISTEMA
tab_robo, tab_comparador = st.tabs(["🤖 Robô de Consulta", "⚖️ Comparador de Planilhas"])

# ================= ABA 1: ROBÔ (CÓDIGO ANTERIOR) =================
with tab_robo:
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

    st.info("Utilize esta aba para consultar os processos no site da ANTT.")
    uploaded_file = st.file_uploader("📂 Planilha de Entrada (.xlsx)", type=['xlsx'], key="upload_robo")

    if uploaded_file and st.button("▶️ Iniciar Robô"):
        if not cpf_input or not senha_input:
            st.error("⚠️ Preencha o Login na barra lateral!")
        else:
            config = ConfigWeb()
            df = pd.read_excel(uploaded_file)
            
            # Limpeza Inicial
            for col in [config.col_processo, config.col_status, config.col_andamento, config.col_auto]:
                 if col in df.columns: df[col] = df[col].astype(str).replace('nan', '')
                 else: df[col] = ""

            if remover_duplicados: df = df.drop_duplicates(subset=[config.col_auto], keep='first')
            if limitador > 0: df = df.head(limitador)

            status_box = st.status("Inicializando...", expanded=True)
            progress_bar = st.progress(0)
            log_placeholder = st.empty()
            
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
                    contador_lote = 0

                    for index, row in df.iterrows():
                        contador_lote += 1
                        if contador_lote >= config.reiniciar_a_cada:
                            status_box.write("🧹 Limpando memória RAM...")
                            driver.quit()
                            gc.collect()
                            time.sleep(2)
                            driver = get_driver()
                            realizar_login(driver, cpf_input, senha_input, config)
                            contador_lote = 0
                        
                        auto = normalizar_auto(row[config.col_auto])
                        status_atual = str(row[config.col_status])
                        
                        if pular_feitos and ("Sucesso" in status_atual or "Processo" in status_atual):
                            st.session_state.logs.insert(0, f"⏭️ {index+1}/{total}: {auto} (Pulado)")
                            log_placeholder.text("\n".join(st.session_state.logs[:10]))
                            progress_bar.progress((index + 1) / total)
                            continue

                        if auto in cache:
                            res = cache[auto]
                            st.session_state.logs.insert(0, f"♻️ {index+1}/{total}: {auto} (Cache)")
                        else:
                            status_box.update(label=f"🔄 [{index+1}/{total}] Consultando: {auto}")
                            res = consultar_auto(driver, auto, config)
                            cache[auto] = res
                        
                        df.at[index, config.col_status] = res['mensagem']
                        if res['status'] == 'sucesso':
                            df.at[index, config.col_processo] = res['dados'].get('processo', '')
                            df.at[index, config.col_andamento] = res['dados'].get('ultimo_andamento', '')
                            icon = "✅"
                        elif res['status'] == 'nao_encontrado': icon = "⚠️"
                        else: icon = "❌"
                        
                        st.session_state.logs.insert(0, f"{icon} {index+1}/{total}: {auto} - {res['mensagem']}")
                        log_placeholder.text("\n".join(st.session_state.logs[:10]))
                        progress_bar.progress((index + 1) / total)
                        st.session_state.df_final = df.copy()

                    status_box.update(label="Concluído!", state="complete")
                    st.success("Finalizado!")
                    download_automatico(df, "Planilha_ANTT_Atualizada.xlsx")

            except Exception as e:
                st.error(f"Erro Crítico: {e}")
            finally:
                if driver: driver.quit()

    if st.session_state.df_final is not None:
        st.divider()
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            st.session_state.df_final.to_excel(writer, index=False)
        st.download_button("📥 Baixar Planilha (Backup)", data=buffer.getvalue(), file_name="Planilha_ANTT_Backup.xlsx")

# ================= ABA 2: COMPARADOR (NOVO CÓDIGO) =================
with tab_comparador:
    st.markdown("### ⚖️ Conciliação de Novos Autos")
    st.markdown("""
    Use esta ferramenta para verificar se há novos autos na planilha **Controle GEAUT** que ainda não estão na planilha de **Entrada**.
    """)

    col1, col2 = st.columns(2)
    with col1:
        file_geaut = st.file_uploader("1. Planilha Controle GEAUT (Fonte)", type=['xlsx'], key="up_geaut")
    with col2:
        file_entrada = st.file_uploader("2. Planilha Entrada (Destino)", type=['xlsx'], key="up_entrada")

    if file_geaut and file_entrada:
        if st.button("🔄 Comparar e Atualizar Planilha de Entrada"):
            try:
                # Carregar Planilhas
                df_geaut = pd.read_excel(file_geaut)
                df_entrada = pd.read_excel(file_entrada)
                
                col_chave = "Auto de Infração"

                # Verificar se a coluna existe em ambas
                if col_chave not in df_geaut.columns or col_chave not in df_entrada.columns:
                    st.error(f"Erro: A coluna '{col_chave}' precisa existir em AMBAS as planilhas.")
                    st.stop()

                # Normalizar para comparação (Maiúsculo, sem espaços)
                geaut_autos = set(df_geaut[col_chave].apply(normalizar_auto))
                entrada_autos = set(df_entrada[col_chave].apply(normalizar_auto))

                # Encontrar Novos Autos (que estão no GEAUT mas não na Entrada)
                novos_autos = geaut_autos - entrada_autos
                qtd_novos = len(novos_autos)

                if qtd_novos == 0:
                    st.success("✅ Tudo atualizado! Não há novos autos para importar.")
                else:
                    st.warning(f"⚠️ Encontrados {qtd_novos} novos autos no GEAUT que não estavam na Entrada.")
                    
                    # Criar DataFrame com os novos autos
                    df_novos = pd.DataFrame({col_chave: list(novos_autos)})
                    
                    # Adicionar colunas extras vazias para manter padrão
                    cols_extras = ['Nº do Processo', 'Status Consulta', 'Último Andamento']
                    for col in cols_extras:
                        df_novos[col] = ""

                    # Concatenar (Adicionar ao final)
                    df_final_entrada = pd.concat([df_entrada, df_novos], ignore_index=True)
                    
                    st.success("✅ Planilha atualizada com sucesso!")
                    
                    # Visualização
                    with st.expander("Ver lista de novos autos adicionados"):
                        st.dataframe(df_novos)
                    
                    # Download
                    download_automatico(df_final_entrada, "entrada_atualizada_com_novos.xlsx")
                    
                    buffer_comp = io.BytesIO()
                    with pd.ExcelWriter(buffer_comp, engine='openpyxl') as writer:
                        df_final_entrada.to_excel(writer, index=False)
                    st.download_button(
                        label="📥 Baixar Planilha Entrada Atualizada",
                        data=buffer_comp,
                        file_name="entrada_atualizada_com_novos.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

            except Exception as e:
                st.error(f"Erro ao processar planilhas: {e}")
