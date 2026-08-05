def _regra_contrato_por_similaridade(self, cliente, equip_nome, contrato, item):
        """Motor Inteligente de Contratos: Usa Normalização Absoluta e Fuzzy Matching"""
        if self._vazio(contrato):
            
            # 1. NORMALIZAÇÃO ABSOLUTA (Mata acentos, cedilhas e espaços duplos antes de ler)
            cliente_limpo = normalizar(str(cliente)).strip()
            
            for termo_original, substituto in SUBSTITUICOES_TERMOS.items():
                # Normalizamos o De-Para também, por segurança
                cliente_limpo = cliente_limpo.replace(normalizar(termo_original), normalizar(substituto))
                
            cliente_limpo = re.sub(r'\s+', ' ', cliente_limpo.replace('-', ' ').replace('/', ' '))
            
            # 2. FILTRO MT (Mantendo o isolamento)
            opcoes_permitidas = []
            for c in self.opcoes_contratos:
                if self._vazio(c): continue
                c_norm = normalizar(str(c)).strip()
                if c_norm == "MT" or c_norm.startswith("MT -") or c_norm.startswith("MT "):
                    if "TRANSPORTE" not in cliente_limpo:
                        continue 
                opcoes_permitidas.append(c)

            # 3. TESTE BIDIRECIONAL COM IA (RapidFuzz)
            melhor_score = 0
            melhor_match = None
            
            for c in opcoes_permitidas:
                # Normaliza o contrato do banco novo (mata os acentos dele também)
                contrato_limpo = normalizar(str(c))
                contrato_limpo = re.sub(r'\s+', ' ', contrato_limpo.replace('-', ' ').replace('/', ' ')).strip()
                
                # Teste Exato Bidirecional (Imune a acentos)
                if contrato_limpo in cliente_limpo:
                    return c, item
                if len(cliente_limpo) >= 4 and cliente_limpo in contrato_limpo:
                    return c, item
                    
                # Teste de Similaridade IA (Lida com letras trocadas e palavras fora de ordem)
                # Exemplo: "RELACOES EXTRERIORES" -> 97% de similaridade
                score = fuzz.token_set_ratio(cliente_limpo, contrato_limpo)
                
                if score > melhor_score:
                    melhor_score = score
                    melhor_match = c

            # Se a IA bater nota >= 95%, é um match quase perfeito!
            # Exigimos que o nome do cliente tenha mais de uma palavra para "SECRETARIA" não puxar tudo
            if melhor_score >= 95 and len(cliente_limpo.split()) > 1:
                return melhor_match, item

            # 4. TESTE DE COBERTURA MATEMÁTICA (Fallback original para Secretarias/Prefeituras)
            palavras_cliente = set(cliente_limpo.split())
            stop_words = {"DE", "DA", "DO", "DAS", "DOS", "SECRETARIA", "DEPARTAMENTO", "ESTADUAL", "MUNICIPAL", "CONTRATO", "SEC", "ADM", "P", "M"}
            palavras_chave_cliente = palavras_cliente - stop_words

            if palavras_chave_cliente:
                maior_score_fallback = 0.0
                melhor_match_fallback = None

                for c in opcoes_permitidas:
                    contrato_limpo = normalizar(str(c)).replace('-', ' ').replace('/', ' ')
                    palavras_chave_contrato = set(contrato_limpo.split()) - stop_words
                    
                    if not palavras_chave_contrato: continue
                    
                    intersecao = palavras_chave_cliente.intersection(palavras_chave_contrato)
                    score_cobertura = len(intersecao) / len(palavras_chave_contrato)
                    
                    # Cobertura Reversa
                    score_reverso = len(intersecao) / len(palavras_chave_cliente)
                    if score_reverso >= 0.99 and len(intersecao) >= 2:
                        score_cobertura = 1.0
                    
                    if score_cobertura == 1.0:
                        return c, item
                        
                    if score_cobertura > 0.7 and score_cobertura > maior_score_fallback:
                        maior_score_fallback = score_cobertura
                        melhor_match_fallback = c

                if melhor_match_fallback:
                    return melhor_match_fallback, item

        return contrato, item