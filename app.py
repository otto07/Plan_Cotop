import streamlit as st
import pandas as pd
import time
import logging
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================
st.set_page_config(page_title="Robô ANTT - Cloud Pro", page_icon="🚛", layout="wide")

@dataclass
class Config:
    """Configurações centralizadas"""
    url_login: str = 'https://appweb1.antt.gov.br/sca/Site/Login.aspx?ReturnUrl=%2fspm%2fSite%2fDefesaCTB%2fConsultaProcessoSituacao.aspx'
    timeout_elemento: int = 20
    
    # Colunas da Planilha
    col_auto: str = 'Auto de Infração'
    col_processo: str = 'Nº do Processo'
    col_data: str = 'Data da Infração'
    col_codigo: str = 'Código da Infração'
    col_fato: str = 'Fato Gerador'
    col_andamento: str = 'Último Andamento'
    col_data_andamento: str = 'Data do Último Andamento'
    col_status: str = 'Status Consulta'

# Logging simplificado para Streamlit
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("ANTT_Bot")

# =============================================================================
# DRIVER MANAGER
# =============================================================================
class WebDriverManager:
    """Gerencia o driver Chrome para Streamlit Cloud"""
    
    @staticmethod
    def criar_driver():
        chrome_options = Options()
        
        # Binários do Streamlit Cloud (instalados via packages.txt)
        chrome_options.binary_location = "/usr/bin/chromium"
        
        # Flags essenciais para container Linux
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            service = Service("/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except Exception as e:
            st.error(f"❌ Erro ao iniciar navegador: {e}")
            st.stop()

# =============================================================================
# AUTENTICAÇÃO
# =============================================================================
class LoginManager:
    """Gerencia autenticação no sistema ANTT"""
    
    def __init__(self, driver, wait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config
    
    def realizar_login(self, usuario: str, senha: str) -> bool:
        """Login otimizado com injeção JavaScript"""
        try:
            self.driver.get(self.config.url_login)
            
            # Etapa 1: Inserir Usuário
            id_user = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_TextBoxUsuario"
            campo_user = self.wait.until(EC.element_to_be_clickable((By.ID, id_user)))
            campo_user.clear()
            campo_user.send_keys(usuario)
            
            # Etapa 2: Clicar OK
            id_btn_ok = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ButtonOk"
            btn_ok = self.driver.find_element(By.ID, id_btn_ok)
            btn_ok.click()
            
            # Etapa 3: Inserir Senha (COM MÚLTIPLAS TÉCNICAS)
            try:
                xpath_senha = "//input[@type='password']"
                campo_senha = self.wait.until(EC.visibility_of_element_located((By.XPATH, xpath_senha)))
                
                # Pausa para ASP.NET carregar scripts
                time.sleep(2)
                
                # Método 1: Digitação normal
                campo_senha.click()
                campo_senha.clear()
                campo_senha.send_keys(senha)
                
                # Método 2: Injeção JavaScript (garante valor mesmo em headless)
                self.driver.execute_script(f"arguments[0].value = '{senha}';", campo_senha)
                
                # Método 3: Dispara eventos para validadores
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", campo_senha)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", campo_senha)
                
                time.sleep(0.5)
                
                # Método 4: Enter direto (evita problemas com botão)
                campo_senha.send_keys(Keys.RETURN)
                
            except Exception as e:
                logger.warning(f"Senha: {e}")
            
            # Etapa 4: Verificar Sucesso
            self.wait.until(
                EC.presence_of_element_located(
                    (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
                )
            )
            return True
            
        except Exception as e:
            logger.error(f"❌ Falha no login: {e}")
            try:
                # Screenshot para debug
                st.image(self.driver.get_screenshot_as_png(), caption="Erro Detectado")
            except:
                pass
            return False

# =============================================================================
# CONSULTOR ANTT
# =============================================================================
class ConsultorANTT:
    """Realiza consultas no sistema ANTT"""
    
    def __init__(self, driver, wait, config: Config):
        self.driver = driver
        self.wait = wait
        self.config = config
    
    def _esperar_dados_preenchidos(self, element_id: str, timeout: int = 10) -> str:
        """Aguarda campo ser preenchido dinamicamente"""
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                elem = self.driver.find_element(By.ID, element_id)
                valor = elem.get_attribute('value')
                if valor and valor.strip():
                    return valor
                time.sleep(0.5)
            except:
                pass
        return ""
    
    def processar_auto(self, auto_infracao: str) -> Dict[str, Any]:
        """Processa um auto de infração completo"""
        resultado = {'status': 'erro', 'dados': {}, 'mensagem': ''}
        janela_principal = self.driver.current_window_handle
        
        try:
            # 1. Inserir número do auto
            campo_busca = self.wait.until(
                EC.element_to_be_clickable(
                    (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_txbAutoInfracao")
                )
            )
            campo_busca.clear()
            time.sleep(0.3)
            campo_busca.send_keys(auto_infracao)
            
            # 2. Pesquisar (com retry)
            encontrou = False
            for tentativa in range(3):
                try:
                    btn_pesquisar = self.driver.find_element(
                        By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_btnPesquisar"
                    )
                    self.driver.execute_script("arguments[0].click();", btn_pesquisar)
                    time.sleep(2)
                    
                    self.wait.until(
                        EC.presence_of_element_located(
                            (By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0")
                        )
                    )
                    encontrou = True
                    break
                except:
                    if "Nenhum registro encontrado" in self.driver.page_source:
                        break
                    logger.debug(f"Tentativa {tentativa+1} falhou")
            
            if not encontrou:
                resultado['status'] = 'nao_encontrado'
                resultado['mensagem'] = 'Auto não localizado'
                return resultado
            
            # 3. Abrir popup de detalhes
            btn_editar = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_gdvAutoInfracao_btnEditar_0"
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_editar)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn_editar)
            
            # 4. Trocar para janela popup
            WebDriverWait(self.driver, 15).until(EC.number_of_windows_to_be(2))
            janelas = self.driver.window_handles
            nova_janela = [j for j in janelas if j != janela_principal][0]
            self.driver.switch_to.window(nova_janela)
            time.sleep(3)
            
            # 5. Extrair dados
            dados = self._extrair_dados_popup()
            
            if dados:
                resultado['status'] = 'sucesso'
                resultado['dados'] = dados
                resultado['mensagem'] = 'Sucesso'
            else:
                resultado['mensagem'] = 'Erro ao ler dados'
            
            # 6. Fechar popup
            self.driver.close()
            self.driver.switch_to.window(janela_principal)
            
            return resultado
            
        except Exception as e:
            resultado['mensagem'] = f'Erro: {str(e)}'
            if len(self.driver.window_handles) > 1:
                try:
                    self.driver.switch_to.window(janela_principal)
                except:
                    pass
            return resultado
    
    def _extrair_dados_popup(self) -> Dict[str, str]:
        """Extrai dados do popup de detalhes"""
        dados = {}
        
        try:
            # Campos básicos
            id_processo = "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbProcesso"
            self.wait.until(EC.visibility_of_element_located((By.ID, id_processo)))
            
            dados['processo'] = self._esperar_dados_preenchidos(id_processo) or \
                               self.driver.find_element(By.ID, id_processo).get_attribute('value')
            
            dados['data_infracao'] = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbDataInfracao"
            ).get_attribute('value')
            
            dados['codigo'] = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbCodigoInfracao"
            ).get_attribute('value')
            
            dados['fato'] = self.driver.find_element(
                By.ID, "ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_txbObservacaoFiscalizacao"
            ).get_attribute('value')
            
            # Extração da tabela de andamentos
            self._extrair_andamentos(dados)
            
            return dados
            
        except Exception as e:
            logger.error(f"Erro extração: {e}")
            return {}
    
    def _extrair_andamentos(self, dados: Dict[str, str]):
        """Extrai última linha da tabela de andamentos"""
        try:
            xpath_tabela = '//*[@id="ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ContentPlaceHolderCorpo_ucDetalheAutoInfracao5083_ucDocumentosDoProcesso442_gdvDocumentosProcesso"]'
            self.wait.until(EC.presence_of_element_located((By.XPATH, xpath_tabela)))
            
            tabela = self.driver.find_element(By.XPATH, xpath_tabela)
            linhas = tabela.find_elements(By.TAG_NAME, "tr")
            
            if len(linhas) > 1:
                ultima_linha = linhas[-1]
                cols = ultima_linha.find_elements(By.TAG_NAME, "td")
                
                if len(cols) >= 4:
                    dados['data_andamento'] = cols[3].text  # 4ª coluna
                    dados['andamento'] = cols[1].text       # 2ª coluna
                elif len(cols) >= 2:
                    dados['data_andamento'] = cols[-1].text
                    dados['andamento'] = cols[0].text
                else:
                    dados['andamento'] = "Formato desconhecido"
                    dados['data_andamento'] = ""
            else:
                dados['andamento'] = "Sem andamentos"
                dados['data_andamento'] = ""
                
        except Exception as e:
            logger.warning(f"Erro ao ler tabela: {e}")
            dados['andamento'] = 'Erro na tabela'
            dados['data_andamento'] = ""

# =============================================================================
# INTERFACE STREAMLIT
# =============================================================================
def main():
    config = Config()
    
    st.title("🚛 Robô ANTT - Consulta Automatizada")
    st.markdown("---")
    
    # Sidebar com instruções
    with st.sidebar:
        st.header("ℹ️ Instruções")
        st.markdown("""
        **Passo a passo:**
        1. Insira usuário e senha ANTT
        2. Faça upload da planilha Excel
        3. Clique em "Iniciar Processamento"
        4. Aguarde a conclusão
        5. Baixe o resultado
        
        **Formato da planilha:**
        - Deve conter coluna "Auto de Infração"
        - Formato: `.xlsx`
        """)
        
        st.markdown("---")
        st.info("💡 **Dica:** Processe lotes de até 50 autos por vez para melhor performance")
    
    # Formulário principal
    col1, col2 = st.columns(2)
    
    with col1:
        usuario = st.text_input("👤 Usuário ANTT", key="usuario")
    
    with col2:
        senha = st.text_input("🔒 Senha ANTT", type="password", key="senha")
    
    arquivo = st.file_uploader(
        "📂 Upload da Planilha", 
        type=['xlsx'],
        help="Planilha deve conter a coluna 'Auto de Infração'"
    )
    
    # Validações
    if not usuario or not senha:
        st.warning("⚠️ Preencha usuário e senha")
        return
    
    if not arquivo:
        st.info("📤 Aguardando upload da planilha...")
        return
    
    # Botão de processamento
    if st.button("🚀 Iniciar Processamento", type="primary", use_container_width=True):
        processar_planilha(arquivo, usuario, senha, config)

def processar_planilha(arquivo, usuario: str, senha: str, config: Config):
    """Fluxo principal de processamento"""
    
    try:
        # 1. Carregar planilha
        with st.spinner("📊 Carregando planilha..."):
            df = pd.read_excel(arquivo)
            
            # Validar coluna obrigatória
            if config.col_auto not in df.columns:
                st.error(f"❌ Coluna '{config.col_auto}' não encontrada na planilha!")
                return
            
            # Criar colunas de saída
            colunas_saida = [
                config.col_processo, config.col_data, config.col_codigo,
                config.col_fato, config.col_andamento, config.col_data_andamento,
                config.col_status
            ]
            for col in colunas_saida:
                if col not in df.columns:
                    df[col] = ""
            
            df = df.astype(object).replace('nan', '')
            
            # Filtrar linhas válidas
            df_filtrado = df[df[config.col_auto].notna() & (df[config.col_auto] != '')]
            total = len(df_filtrado)
            
            st.success(f"✅ Planilha carregada: {total} autos para processar")
        
        # 2. Inicializar driver
        with st.spinner("🌐 Inicializando navegador..."):
            driver = WebDriverManager.criar_driver()
            wait = WebDriverWait(driver, config.timeout_elemento)
        
        # 3. Fazer login
        with st.spinner("🔐 Realizando login..."):
            login_manager = LoginManager(driver, wait, config)
            
            if not login_manager.realizar_login(usuario, senha):
                st.error("❌ Falha no login. Verifique suas credenciais.")
                driver.quit()
                return
            
            st.success("✅ Login realizado com sucesso!")
        
        # 4. Processar autos
        consultor = ConsultorANTT(driver, wait, config)
        
        # Containers para feedback visual
        progress_bar = st.progress(0)
        status_text = st.empty()
        preview_container = st.expander("📋 Preview dos Resultados", expanded=True)
        
        sucesso_count = 0
        erro_count = 0
        
        for idx, (original_idx, row) in enumerate(df_filtrado.iterrows()):
            auto = str(row[config.col_auto]).strip()
            
            # Atualiza status
            status_text.markdown(f"**Processando:** `{auto}` ({idx+1}/{total})")
            
            # Processa auto
            resultado = consultor.processar_auto(auto)
            
            # Atualiza dataframe
            df.at[original_idx, config.col_status] = str(resultado['mensagem'])
            
            if resultado['status'] == 'sucesso':
                d = resultado['dados']
                df.at[original_idx, config.col_processo] = str(d.get('processo', ''))
                df.at[original_idx, config.col_data] = str(d.get('data_infracao', ''))
                df.at[original_idx, config.col_codigo] = str(d.get('codigo', ''))
                df.at[original_idx, config.col_fato] = str(d.get('fato', ''))
                df.at[original_idx, config.col_andamento] = str(d.get('andamento', ''))
                df.at[original_idx, config.col_data_andamento] = str(d.get('data_andamento', ''))
                sucesso_count += 1
            else:
                erro_count += 1
            
            # Atualiza barra de progresso
            progress_bar.progress((idx + 1) / total)
            
            # Mostra preview
            with preview_container:
                st.dataframe(
                    df[df[config.col_status] != ''].tail(10),
                    use_container_width=True
                )
            
            time.sleep(0.5)  # Delay entre requisições
        
        # 5. Finalização
        driver.quit()
        
        status_text.empty()
        st.markdown("---")
        st.success(f"🎉 **Processamento Concluído!**")
        
        # Estatísticas
        col1, col2, col3 = st.columns(3)
        col1.metric("✅ Sucesso", sucesso_count)
        col2.metric("❌ Erros", erro_count)
        col3.metric("📊 Total", total)
        
        # 6. Download
        output = BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        st.download_button(
            label="📥 Baixar Planilha Completa",
            data=output,
            file_name=f"ANTT_Resultado_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )
        
    except Exception as e:
        st.error(f"❌ **Erro Crítico:** {str(e)}")
        logger.exception("Erro no processamento")

if __name__ == "__main__":
    main()
