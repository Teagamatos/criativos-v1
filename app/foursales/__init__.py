"""Geração do PDF de divulgação de vagas Foursales (LAB-2239).

Mesmo desenho do fluxo Salesjobs: o n8n resolve os dados da vaga e chama
POST /generate-foursales; aqui escolhemos a foto, montamos a capa sobre o
template do Figma, renderizamos o PDF de 3 páginas e anexamos no card.
"""
