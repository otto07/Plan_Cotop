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
from selenium.common.exceptions import TimeoutException

# ================= CONFIGURAÇÃO DA PÁGINA =================
st.set_page_config(page_title="Robô ANTT - Consulta Multas", layout="wide")

# ================= CLASSE DE CONFIGURAÇÃO =================
class ConfigWeb:
    def __init__(self):
        # URL de Login específica fornecida pelo usuário
        self.url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        # URL alvo da consulta (após login)
        self.url_consulta = 'https://appweb1.antt.gov.br/spm/Site/DefesaCTB/ConsultaProcessoSituacao.aspx'
        
        self.col_auto = 'Auto de Infração'
        self.col_processo = 'Nº do Processo'
        self.col_status = 'Status Consulta'
        self.col_andamento = 'Último Andamento'

# ================= INFRAESTRUTURA =================
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-bloqueio básico
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    return webdriver.Chrome(options=chrome_options)

# ================= LÓGICA DE LOGIN HÍBRIDA =================
def realizar_login(driver, usuario, senha, config):
    """
    Tenta logar tanto no formulário legado da ANTT quanto no Gov.br,
    dependendo de qual página carregar.
    """
    wait = WebDriverWait(driver, 15)
    
    try:
        driver.get(config.url_login)
        time.sleep(3) # Espera carregar
        
        # Cenário 1: Login Legado ANTT (Campos na tela direto)
        # Procura por inputs de texto e password genéricos se os IDs mudarem
        try:
            # Verifica se estamos na URL do SCA (Sistema de Controle de Acesso)
            if "sca/Site/Login" in driver.current_url:
                st.info("Detectado sistema de login SCA/ANTT.")
                
                # Tenta encontrar campo de usuário (geralmente txtUsuario ou Login1_UserName)
                campo_user = driver.find_element(By.XPATH, "//input[contains(@name, 'Usuario') or contains(@id, 'User')]")
                campo_user.clear()
                campo_user.send_keys(usuario)
                
                # Tenta encontrar campo senha
                campo_pass = driver.find_element(By.XPATH, "//input[@type='password']")
                campo_pass.clear()
                campo_pass.send_keys(senha)
                
                # Tenta encontrar botão entrar
                btn_entrar = driver.find_element(By.XPATH, "//input[@type='submit'] | //a[contains(@id, 'Login')]")
                btn_entrar.click()
                
                time.sleep(5)
                
                if "ConsultaProcessoSituacao" in driver.current_url:
                    return True, "Login ANTT realizado com sucesso!"
        except Exception as e_antt:
            print(f"Não foi login ANTT direto: {e_antt}")

        # Cenário 2: Redirecionamento para Gov.br
        if "sso.acesso.gov.br" in driver.current_url:
            st.info("Redirecionado para Gov.br. Tentando login...")
            
            # CPF
            campo_cpf = wait.until(EC.presence_of_element_located((By.ID, "accountId")))
            campo_cpf.clear()
            campo_cpf.send_keys(usuario)
            
            driver.find_element(By.XPATH, "//button[contains(text(), 'Continuar')]").click()
            time.sleep(3)
            
            # Senha
            campo_senha = wait.until(EC.presence_of_element_located((By.ID, "password")))
            campo_senha.send_keys(senha)
            
            driver.find_element(By.ID, "submit-button").click()
            time.sleep(5)

        # Validação Final
        if "ConsultaProcessoSituacao" in driver.current_url:
            return True, "Login Confirmado!"
        
        # Tentar forçar a ida para a página de consulta após logar
        driver.get(config.url_consulta)
        time.sleep(3)
        if "ConsultaProcessoSituacao" in driver.current_url:
             return True, "Login realizado (via redirecionamento)."
             
        return False, f"Não foi possível confirmar o login. URL atual: {driver.current_url}"

    except Exception as e:
        return False, f"Erro crítico no login: {str(e)}"

# ================= LÓGICA DE CONSULTA =================
def consultar_auto(driver, auto, config):
    resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 8)
    
    try:
        # Garantir URL
        if "ConsultaProcessoSituacao" not in driver.current_url:
             driver.get(config.url_consulta)
        
        # Preencher Campo
        campo = wait.until(EC.presence_of_element_located(
            (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
        ))
        campo.clear()
        campo.send_keys(auto)
        
        # Botão Pesquisar
        driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar").click()
        time.sleep(2)
        
        # Verificar se achou
        src = driver.page_source.lower()
        if "nenhum registro" in src or "não encontrado" in src:
            resultado['status'] = 'nao_encontrado'
            resultado['mensagem'] = 'Auto não localizado'
            return resultado

        # Clicar no Editar (Lápis/Botão)
        try:
            # Tenta clicar no primeiro botão de editar que aparecer na grid
            btn_editar = driver.find_element(By.XPATH, "//input[contains(@id, 'btnEditar')] | //a[contains(@title, 'Editar')]")
            btn_editar.click()
            time.sleep(2)
            
            # Gerenciar Janelas (Pop-up)
            janela_principal = driver.window_handles[0]
            janela_detalhe = None
            
            if len(driver.window_handles) > 1:
                janela_detalhe = driver.window_handles[-1]
                driver.switch_to.window(janela_detalhe)
            
            # Extrair Dados
            dados = {}
            try:
                # Processo
                try:
                    elem_proc = driver.find_element(By.XPATH, "//*[contains(@id, 'txbProcesso')]")
                    dados['processo'] = elem_proc.get_attribute('value')
                except:
                    dados['processo'] = "Erro ID Processo"

                # Andamento (Tenta pegar da tabela de histórico)
                try:
                    # Pega a última linha da tabela de tramitação
                    linhas = driver.find_elements(By.XPATH, "//table[contains(@class, 'tabela-conteudo')]//tr")
                    if len(linhas) > 1:
                        # Assume que a última linha é o andamento mais recente
                        colunas = linhas[-1].find_elements(By.TAG_NAME, "td")
                        if len(colunas) >= 2:
                            dados['ultimo_andamento'] = colunas[1].text
                        else:
                            dados['ultimo_andamento'] = linhas[-1].text
                    else:
                        dados['ultimo_andamento'] = "Sem andamentos visíveis"
                except:
                    dados['ultimo_andamento'] = "Tabela não encontrada"

            except Exception as e_extracao:
                dados['processo'] = f"Erro parcial: {str(e_extracao)[:20]}"

            resultado['dados'] = dados
            resultado['status'] = 'sucesso'
            resultado['mensagem'] = 'Sucesso'
            
            # Fechar Pop-up
            if janela_detalhe:
                driver.close()
                driver.switch_to.window(janela_principal)
                
        except Exception as e_botao:
            resultado['status'] = 'erro_interacao'
            resultado['mensagem'] = f'Achou mas falhou detalhe: {str(e_botao)[:30]}'

    except Exception as e:
        resultado['mensagem'] = f"Erro geral: {str(e)[:30]}"
        
    return resultado

# ================= INTERFACE GRÁFICA =================
st.title("🕵️ Robô ANTT - Consulta Web")

with st.sidebar:
    st.header("🔐 Credenciais ANTT")
    cpf_input = st.text_input("Usuário/CPF")
    senha_input = st.text_input("Senha", type="password")
    
    st.divider()
    st.header("⚙️ Controle")
    # LIMITADOR DE LINHAS (BOTÃO PARAR INDIRETO)
    st.info("Use 0 para processar TUDO. Use um número (ex: 5) para testar apenas as primeiras linhas e parar.")
    limite_linhas = st.number_input("Limite de linhas para teste:", min_value=0, value=5)

uploaded_file = st.file_uploader("📂 Carregar Planilha (entrada.xlsx)", type=['xlsx'])

if uploaded_file and st.button("🚀 Iniciar Processamento"):
    if not cpf_input or not senha_input:
        st.error("⚠️ Preencha Usuário e Senha antes de iniciar.")
    else:
        config = ConfigWeb()
        df = pd.read_excel(uploaded_file)
        
        # APLICA O LIMITADOR
        if limite_linhas > 0:
            st.warning(f"⚠️ MODO TESTE ATIVO: Processando apenas as primeiras {limite_linhas} linhas.")
            df = df.head(limite_linhas)
        
        # Limpeza e Preparação
        cols_limpar = [config.col_processo, config.col_status, config.col_andamento]
        for col in cols_limpar:
             df[col] = df[col].astype(str) if col in df.columns else ""
        
        # UI
        status_box = st.status("Inicializando sistema...", expanded=True)
        progress_bar = st.progress(0)
        log_box = st.expander("📜 Logs Detalhados", expanded=True)
        logs = []
        
        driver = get_driver()
        
        try:
            status_box.write("🔐 Tentando realizar login...")
            sucesso_login, msg_login = realizar_login(driver, cpf_input, senha_input, config)
            
            if not sucesso_login:
                status_box.update(label="❌ Erro no Login", state="error")
                st.error(msg_login)
                try:
                    driver.save_screenshot("debug_login.png")
                    st.image("debug_login.png", caption="Tela no momento da falha")
                except: pass
            else:
                status_box.write("✅ Login realizado! Iniciando varredura...")
                time.sleep(1)
                
                total = len(df)
                sucessos = 0
                
                for index, row in df.iterrows():
                    auto = str(row[config.col_auto])
                    status_box.update(label=f"🔄 Processando {index+1}/{total}: {auto}", state="running")
                    
                    res = consultar_auto(driver, auto, config)
                    
                    # Atualiza Planilha
                    df.at[index, config.col_status] = res['mensagem']
                    
                    if res['status'] == 'sucesso':
                        sucessos += 1
                        df.at[index, config.col_processo] = res['dados'].get('processo', '')
                        df.at[index, config.col_andamento] = res['dados'].get('ultimo_andamento', '')
                        icon = "✅"
                    elif res['status'] == 'nao_encontrado':
                        icon = "⚠️"
                    else:
                        icon = "❌"
                    
                    # Log
                    log_msg = f"{icon} [{index+1}] {auto}: {res['mensagem']}"
                    if res['status'] == 'sucesso':
                         log_msg += f" | Proc: {res['dados'].get('processo')}"
                    
                    logs.insert(0, log_msg) # Adiciona no topo
                    log_box.write("\n\n".join(logs[:10])) # Mostra últimos 10
                    progress_bar.progress((index + 1) / total)
                
                status_box.update(label="🏁 Processamento Finalizado!", state="complete")
                
                # Download Final
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)
                
                st.success(f"Concluído! {sucessos}/{total} processados com sucesso.")
                st.download_button(
                    label="📥 Baixar Planilha Atualizada",
                    data=buffer.getvalue(),
                    file_name="antt_resultado.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        except Exception as e:
            st.error(f"Erro fatal durante execução: {e}")
        finally:
            driver.quit()
