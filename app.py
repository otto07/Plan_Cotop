import streamlit as st
import pandas as pd
import time
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
st.set_page_config(
    page_title="Robô ANTT - Consulta Pro",
    page_icon="🚛",
    layout="wide"
)

# =============================================================================
# FUNÇÕES CORE (SELENIUM)
# =============================================================================

def get_driver():
    """Inicializa o WebDriver em modo Headless (compatível com servidores/background)"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Roda sem janela visual
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detecção básico
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def realizar_login(driver, usuario, senha):
    """
    Realiza login automatizado (necessário para Streamlit, pois não há interação manual)
    """
    try:
        url_login = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
        driver.get(url_login)
        wait = WebDriverWait(driver, 10)

        # 1. Inserir Usuário
        # ID padrão do ASP.NET da ANTT para o usuário
        id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
        campo_user = wait.until(EC.element_to_be_clickable((By.ID, id_user)))
        campo_user.clear()
        campo_user.send_keys(usuario)

        # 2. Clicar OK (Botão inicial)
        id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
        btn_ok = driver.find_element(By.ID, id_btn_ok)
        btn_ok.click()
        
        # 3. Tratamento de Senha (se houver campo de senha)
        try:
            time.sleep(2)
            # Tenta encontrar campo de senha genérico ou pelo ID se soubermos
            campo_senha = driver.find_element(By.XPATH, "//input[@type='password']")
            campo_senha.clear()
            campo_senha.send_keys(senha)
            
            # Clica no botão de confirmar novamente
            btn_ok.click()
        except:
            # Se não pediu senha (login direto) ou erro no campo, segue o fluxo
            pass
            
        # 4. Verificar sucesso (Aparecimento do campo de busca)
        wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        return True
    except Exception as e:
        st.error(f"Erro no login: {str(e)}")
        return False

def esperar_dados_preenchidos(driver, element_id, timeout=10):
    """Função auxiliar para aguardar o dado aparecer no campo (Lógica do script local)"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            elem = driver.find_element(By.ID, element_id)
            valor = elem.get_attribute('value')
            if valor and valor.strip() != "":
                return valor
            time.sleep(0.5)
        except:
            pass
    return ""

def consultar_processo(driver, auto_infracao):
    """
    Lógica PRINCIPAL portada do seu script local.
    """
    resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
    wait = WebDriverWait(driver, 20)
    janela_principal = driver.current_window_handle
    
    try:
        # 1. Limpeza e Inserção
        campo_busca = wait.until(EC.element_to_be_clickable((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")))
        campo_busca.clear()
        campo_busca.send_keys(auto_infracao)
        
        # 2. Pesquisar (com Retry e Click JS)
        encontrou = False
        for tentativa in range(3):
            try:
                btn_pesquisar = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar")
                driver.execute_script("arguments[0].click();", btn_pesquisar)
                
                time.sleep(2)
                
                # Verifica botão editar
                wait.until(EC.presence_of_element_located((By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")))
                encontrou = True
                break
            except:
                if "Nenhum registro encontrado" in driver.page_source:
                    break
        
        if not encontrou:
            resultado['status'] = 'nao_encontrado'
            resultado['mensagem'] = 'Auto não localizado'
            return resultado

        # 3. Abrir Pop-up
        btn_editar = driver.find_element(By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_editar)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", btn_editar)
        
        # 4. Troca de Janela
        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))
        janelas = driver.window_handles
        nova_janela = [j for j in janelas if j != janela_principal][0]
        driver.switch_to.window(nova_janela)
        
        time.sleep(3) # Espera técnica crítica
        
        # 5. Extração de Dados
        dados = {}
        try:
            # IDs
            id_processo = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            id_data = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao"
            id_codigo = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao"
            id_fato = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao"

            # Espera inteligente
            wait.until(EC.visibility_of_element_located((By.ID, id_processo)))
            dados['processo'] = esperar_dados_preenchidos(driver, id_processo)
            
            # Fallback
            if not dados['processo']:
                 dados['processo'] = driver.find_element(By.ID, id_processo).get_attribute('value')

            dados['data_infracao'] = driver.find_element(By.ID, id_data).get_attribute('value')
            dados['codigo'] = driver.find_element(By.ID, id_codigo).get_attribute('value')
            dados['fato'] = driver.find_element(By.ID, id_fato).get_attribute('value')

            # Tabela (Lógica da 4ª Coluna)
            try:
                xpath_tabela = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
                wait.until(EC.presence_of_element_located((By.XPATH, xpath_tabela)))
                
                tabela = driver.find_element(By.XPATH, xpath_tabela)
                linhas = tabela.find_elements(By.TAG_NAME, "tr")
                
                if len(linhas) > 1:
                    ultima_linha = linhas[-1]
                    cols = ultima_linha.find_elements(By.TAG_NAME, "td")
                    
                    if len(cols) >= 4:
                        # CORREÇÃO: Pega a 4ª Coluna (Índice 3)
                        dados['data_andamento'] = cols[3].text
                        dados['andamento'] = cols[1].text
                    elif len(cols) >= 2:
                        dados['data_andamento'] = cols[-1].text
                        dados['andamento'] = cols[0].text
                    else:
                         dados['andamento'] = 'Tabela fora do padrão'
            except:
                dados['andamento'] = 'Sem andamentos'
                
            resultado['status'] = 'sucesso'
            resultado['dados'] = dados
            resultado['mensagem'] = 'Sucesso'

        except Exception as e:
            resultado['mensagem'] = f'Erro leitura: {str(e)}'

        # 6. Fechar e Voltar
        driver.close()
        driver.switch_to.window(janela_principal)
        return resultado

    except Exception as e:
        resultado['mensagem'] = f'Erro fluxo: {str(e)}'
        # Tenta recuperar foco
        if len(driver.window_handles) > 1:
            try: driver.switch_to.window(janela_principal)
            except: pass
        return resultado

# =============================================================================
# INTERFACE DO USUÁRIO (STREAMLIT)
# =============================================================================

st.title("🚛 Robô ANTT - Consulta e Comparação")

tab1, tab2 = st.tabs(["🔍 Consulta Automática", "📊 Comparação de Planilhas"])

# --- ABA 1: CONSULTA ---
with tab1:
    st.markdown("### Parâmetros de Acesso")
    st.info("O navegador rodará em segundo plano. Insira as credenciais abaixo.")
    
    col_login1, col_login2 = st.columns(2)
    with col_login1:
        usuario = st.text_input("Usuário ANTT")
    with col_login2:
        senha = st.text_input("Senha ANTT", type="password")
    
    uploaded_file = st.file_uploader("Carregar planilha de entrada (.xlsx)", type="xlsx")
    
    if uploaded_file and usuario: # Senha pode ser opcional dependendo do sistema
        if st.button("🚀 Iniciar Consulta em Massa"):
            try:
                df = pd.read_excel(uploaded_file)
                
                # Normalização e preparação (igual ao script local)
                cols_necessarias = ['Nº do Processo', 'Data da Infração', 'Código da Infração', 
                                    'Fato Gerador', 'Último Andamento', 'Data do Último Andamento', 
                                    'Status Consulta']
                for col in cols_necessarias:
                    if col not in df.columns: df[col] = ""
                
                df = df.astype(object)
                df = df.replace('nan', '')

                # UI de Progresso
                progress_bar = st.progress(0)
                status_text = st.empty()
                st_dataframe = st.empty() # Placeholder para mostrar dados atualizando
                
                # Inicia Driver
                driver = get_driver()
                
                if realizar_login(driver, usuario, senha):
                    st.success("Login realizado (sistema acessado)!")
                    
                    total = len(df)
                    for index, row in df.iterrows():
                        auto = str(row['Auto de Infração']).strip()
                        
                        if pd.isna(auto) or auto == '' or auto == 'nan':
                            continue
                        
                        # Atualiza UI
                        status_text.text(f"Processando [{index+1}/{total}]: {auto}...")
                        
                        # Chama a função robusta
                        res = consultar_processo(driver, auto)
                        
                        # Salva resultados
                        df.at[index, 'Status Consulta'] = str(res['mensagem'])
                        
                        if res['status'] == 'sucesso':
                            d = res['dados']
                            df.at[index, 'Nº do Processo'] = str(d.get('processo', ''))
                            df.at[index, 'Data da Infração'] = str(d.get('data_infracao', ''))
                            df.at[index, 'Código da Infração'] = str(d.get('codigo', ''))
                            df.at[index, 'Fato Gerador'] = str(d.get('fato', ''))
                            df.at[index, 'Último Andamento'] = str(d.get('andamento', ''))
                            df.at[index, 'Data do Último Andamento'] = str(d.get('data_andamento', ''))
                        
                        # Atualiza barra e tabela preview
                        progress_bar.progress((index + 1) / total)
                        st_dataframe.dataframe(df.head(index+1)) # Mostra progresso visual
                    
                    st.success("Processamento concluído!")
                    
                    # Botão de Download
                    output = BytesIO()
                    df.to_excel(output, index=False)
                    output.seek(0)
                    
                    st.download_button(
                        label="📥 Baixar Planilha Atualizada",
                        data=output,
                        file_name="Resultado_ANTT.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("Falha no login ou sistema indisponível.")
                
                driver.quit()

            except Exception as e:
                st.error(f"Erro crítico: {e}")

# --- ABA 2: COMPARAÇÃO ---
with tab2:
    st.header("Comparação de Planilhas")
    
    col_a, col_b = st.columns(2)
    with col_a:
        arquivo_antigo = st.file_uploader("Planilha Antiga (Referência)", type=["xlsx", "csv"], key="antiga")
    with col_b:
        arquivo_novo = st.file_uploader("Planilha Nova (Recente)", type=["xlsx", "csv"], key="nova")

    if st.button("Comparar Planilhas"):
        if arquivo_antigo and arquivo_novo:
            try:
                df_antigo = pd.read_excel(arquivo_antigo) if arquivo_antigo.name.endswith('xlsx') else pd.read_csv(arquivo_antigo)
                df_novo = pd.read_excel(arquivo_novo) if arquivo_novo.name.endswith('xlsx') else pd.read_csv(arquivo_novo)

                if "Auto de Infração" not in df_antigo.columns or "Auto de Infração" not in df_novo.columns:
                    st.error("A coluna 'Auto de Infração' é obrigatória em ambas.")
                else:
                    # Renomeia para comparação
                    df_antigo = df_antigo.rename(columns={"Último Andamento": "Status_Antigo", "Data do Último Andamento": "Data_Antiga"})
                    df_novo = df_novo.rename(columns={"Último Andamento": "Status_Novo", "Data do Último Andamento": "Data_Novo"})

                    # Merge
                    df_resultado = pd.merge(
                        df_novo, 
                        df_antigo[['Auto de Infração', 'Status_Antigo', 'Data_Antiga']], 
                        on='Auto de Infração', 
                        how='left'
                    )

                    def verificar_mudanca(row):
                        status_antigo = str(row['Status_Antigo']).strip()
                        status_novo = str(row['Status_Novo']).strip()
                        
                        if pd.isna(row['Status_Antigo']) or status_antigo in ['nan', '']:
                            return "Novo Processo"
                        if status_antigo != status_novo:
                            return "Houve Mudança"
                        return "Sem Mudança"

                    df_resultado['Resultado Comparação'] = df_resultado.apply(verificar_mudanca, axis=1)

                    mudancas = df_resultado[df_resultado['Resultado Comparação'] == "Houve Mudança"]
                    st.metric("Processos com Mudança", len(mudancas))
                    
                    if len(mudancas) > 0:
                        st.dataframe(mudancas)

                    output_comp = BytesIO()
                    df_resultado.to_excel(output_comp, index=False)
                    output_comp.seek(0)
                    
                    st.download_button(
                        label="📥 Baixar Relatório Comparativo",
                        data=output_comp,
                        file_name="Relatorio_Comparacao.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

            except Exception as e:
                st.error(f"Erro ao processar: {e}")
