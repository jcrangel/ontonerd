import pickle
from typing import List,Dict


from dkoulinker.dataset_creation.utils import get_clean_tokens, preprocess
from nltk.corpus import stopwords
from spacy.lang.en import English
from flair.data import Sentence
import time
import numpy as np
from dkoulinker.entity_ranking import EntityRanking
from dkoulinker.utils import (_print_colorful_text, is_overlaping, log)
from dkoulinker.tokenization import SegtokSentenceSplitter

import pprint

class EntityLinker:
    """ The entity linker, takes text and returns parts of the text
        that could be liked to an entity id. 


        :param mention2pem: A dictionary that contains the commoness P(e|m) ,where e is
        the entity and m the mention. It should have format:

        a['mention']:{'entityID1': p(e|m),'entityID2': p(e|m)} 
        a['reproduction']:{'GO:0000003': 1.0} 

        :type mention2pem: Dict
        :param ranking_strategy: [description]
        :type ranking_strategy: EntityRanking
        :param ner_model: [description], defaults to None

        :type ner_model: [type], Flair model:'flair', or 
        'bert_transformers_pipeline' for bert transformers pipeline. 
        Example:: 
            ner_pipeline = pipeline('ner', model=output_dir, tokenizer=output_dir,ignore_labels=['O'],
            grouped_entities=True,ignore_subwords=True)

        :param ner_model_type: [description], defaults to 'flair'
        :type ner_model_type: str, optional
        :param prune_overlapping_method: [description], defaults to 'best_score'
        :type prune_overlapping_method: str, optional
    """
    def __init__(self, 
                mention2pem:Dict, 
                # mention_freq,
                # collection_size_terms,
                ranking_strategy: EntityRanking,
                entity2description=None, 
                ner_model=None,
                 ner_model_type='flair',  # or bert_transformers_pipeline
                prune_overlapping_method='best_score',
                use_ner_dict=True,
                ):

        self.mention2pem = mention2pem

        
        self.entity2description = entity2description
        self.ranking_strategy = ranking_strategy
        #TODO maybe strategy pattern is better here
        self.nlp = English()
        self.nlp.add_pipe("sentencizer")
        self.prune_overlapping_method = prune_overlapping_method
        self.ner_model_type = ner_model_type
        
        self.ner_model = ner_model
        self.use_ner_dict = use_ner_dict
        self.banned_mentions = ['s']
        # ncpu = cpu_count()
        # print('Creating multiprocessing pool of {} size '.format(ncpu))
        # self.pool = Pool(int(ncpu/2))

        if ner_model_type == 'flair':
            self.sentence_splitter = SegtokSentenceSplitter()

    def link_entities_par(self, docs, use_ner=True):
        """The same that in link_entities but process several documents in parallel.

        :param docs: [description]
        :type docs: [type]
        :param use_ner: [description], defaults to True
        :type use_ner: bool, optional
        """
        pass

    def link_entities(self,text,use_ner=True):
        """
        Process the query, find mentions and for each mention show the top-k 
        example return:
        
        [{'text': 'ammonium salt',
        'end_pos': 24,
        'start_pos': 11,
        'entities': [('CHEBI:47704', 35.25677820125997)],
        'best_entity': ('CHEBI:47704', 35.25677820125997)},
        {'text': 'reproduction',
        'end_pos': 68,
        'start_pos': 56,
        'entities': [('GO:0000003', 5.114009083705022,'Description')],
        'best_entity': ('GO:0000003', 5.114009083705022)}]

        """
        # _text = preprocess(text)
        # doc = self.nlp(text)



        ner_mentions = [] #a list of dicts

        #The text is divided into sentences and NER object search for mentions in each one
        #Neither spacy or nltk are give the correct boundaries,  they remove trailing spaces.
        # split() for now 

        if self.ner_model_type =='flair':
            ner_mentions = self.get_ner_mentions_flair(text,
                                                  tagger=self.ner_model,
                                                       splitter=self.sentence_splitter)
        else:
            last_sen_size = 0
            for sent in text.split('.'):
                if sent == '': #text ending with '.', give empty sentence 
                    continue
                log('Analysing sentence:',sent)
                ner_mentions_textonly_sentence,ner_mentions_sentence = get_mentions_ner(
                    sent,
                    self.ner_model,
                    model_type=self.ner_model_type)

                if len(ner_mentions_sentence)>0:
                    for ment in ner_mentions_sentence:

                        ment['start_pos']+=last_sen_size
                        ment['end_pos']+=last_sen_size

                    #Skip mentions not in dictionary
                        if ment['text'] in self.mention2pem:
                            ner_mentions.append(ment)
                #Last text lenght plus 1 for accounting the '.'
                last_sen_size += len(sent) + 1 
                # log('NER mentions:',ner_mentions)

        #For each token find if some is a mention. Search the dictionary of mentions. 
        #TODO find text_tokens positions in text
        clean_text_tokens = get_clean_tokens(text,self.nlp)
        tokendict_mentions = []
        if self.use_ner_dict:
            tokendict_mentions = self.get_mentions_by_tokens_and_dict(text)
        # log('token mentions',tokendict_mentions)
        #combine the mentions found by the NER system and the ones found by
        #tokenization and dict searching.
        #1 Mention phase
        mentions = ner_mentions + tokendict_mentions
        #Also delete repetitions: https://stackoverflow.com/questions/11092511/python-list-of-unique-dictionaries
        mentions = [dict(s) for s in set(frozenset(d.items())
                                        for d in mentions)]

        log("Analizing mentions:")
        # _print_colorful_text(text,mentions)
        #Score entities for each mention

        interpretations = self.ranking_strategy.get_interpretations(clean_text_tokens,mentions)

        #Insert entity description before return     
        # log(interpretations)
        # return interpretations
        if self.entity2description is None:
    
            return self.prune_overlapping_entities(interpretations,method= self.prune_overlapping_method)
        else:
            return self._add_descriptions(self.prune_overlapping_entities(
                interpretations, method=self.prune_overlapping_method))

    def get_ner_mentions_flair(self,text,tagger,splitter):

        
        # use splitter to split text into list of sentences
        plain_sentences, sentences = splitter.split(text)

        # predict tags for sentences
        # tagger = SequenceTagger.load('ner')
        tagger.predict(sentences)
        
        ner_mentions = []  # a list of dicts
        last_sen_size = 0
        for i, sentence in enumerate(sentences):
            # if len(sentence) == 0:
            #     continue
            # print(len(sentence))
            # print(sentence.to_tagged_string())
            ner_mentions_textonly_sentence, ner_mentions_sentence = proc_flair_sentence(
                sentence)
            if len(ner_mentions_sentence) > 0:
                for ment in ner_mentions_sentence:

                    ment['start_pos'] += last_sen_size
                    ment['end_pos'] += last_sen_size

                #Skip mentions not in dictionary
                    if ment['text'] in self.mention2pem:
                        ner_mentions.append(ment)
        #Last text lenght plus 1 for accounting the '.'
            last_sen_size += len(plain_sentences[i]) + 1
        
        return ner_mentions


    def _add_descriptions(self,interpretations):
        """Add the descriptions from entity2desc into the 'entities' field

        :param interpretations: [description]
        :type interpretations: [type]
        """
        for ents in interpretations: 
            entities = ents['entities']
            
            # [['UBERON:0001007', 0.8700926733965282],
            #  ['UBERON:0001555', 0.7340052681185107],
            #     ['UBERON:0004907', 0.36037230161509565],
            #     ['MA:0000917', 0.23101364089906892],
            #     ['ZFA:0000112', 0.3708896865541044]],
            new_entities= []
            for id_,score in entities:
                new_entities.append([id_,score,
                ' '.join(self.entity2description[id_]) ])
                #After: [['UBERON:0001007', 0.8700926733965282,'desc']
            
            ents['entities'] = new_entities

        return interpretations

    def get_mentions_by_tokens_and_dict(self, text:str)->Dict:
        #tokenize and check if mentions exist in the mention dictionary
        nlp = self.nlp
        text_tokens = []
        doc = nlp(text)
        all_stopwords = nlp.Defaults.stop_words
        for token in doc:
            if ((not token.is_punct) 
            and (token.text not in all_stopwords)
            and (token.text in self.mention2pem)
            and not token.text in self.banned_mentions):

                text_tokens.append({
                    'text': token.text,
                    'start_pos': token.idx,
                    'end_pos': token.idx+len(token.text),
                })
        
        return text_tokens
    
    def prune_overlapping_entities(self,interpretations:List[Dict],method='best_score')->List[Dict]:
        """Detect overlapping entities by it position in text. 


        :param interpretations: [description]
        :type interpretations: List[Dict]
        :param method:
        Methods:
            'best_score' choose only the entity with best score over two overlapping text.
            'large_text' choose only the entity with large text score over two overlapping text.
        :type method: str, optional
        :return: [description]
        :rtype: List[Dict]
        """
        new_interpretations=[]
        overlapping_indices=[]
        interpretations.sort(key=lambda x: x['start_pos'])
        for i in range(0,len(interpretations)):
            if i in overlapping_indices:
                continue
            best_interp = interpretations[i]
            log(overlapping_indices)
            log(i, 'best', best_interp['text'], best_interp['best_entity'])
            for j in range(i+1,len(interpretations)):

                other_interp = interpretations[j]
                log(j, 'other', other_interp['text'], other_interp['best_entity'])
                best_interval = [best_interp['start_pos'],best_interp['end_pos']]
                other_interval = [other_interp['start_pos'],other_interp['end_pos']]

                #Is overlapping
                if is_overlaping(best_interval,other_interval) and j not in overlapping_indices:
                    log('overlap!')
                    overlapping_indices.append(j)
                    overlapping_indices.append(i)
                    #comparing scores
                    if method =='best_score':             
                        if best_interp['best_entity'][1] < other_interp['best_entity'][1]:
                            best_interp = other_interp
                    elif method =='large_text':
                        if len(best_interp['text']) < len(other_interp['text']):
                            best_interp = other_interp
                    else:
                        raise('Unknow method')
                        


            new_interpretations.append(best_interp)
        
        return new_interpretations

# def prune_overlapping_entities2(self, interpretations: List[Dict], method='best_score') -> List[Dict]:
#     if len(interpretations) < 1:
#         return interpretations
#     #sort the intervals by its first value
#     interpretations.sort(key=lambda x: x['start_pos'])

#     merged_list = []
#     merged_list.append(interpretations[0])
#     for i in range(1, len(interpretations)):
#         pop_element = merged_list.pop()

#         pop_interval = [pop_element['start_pos'], pop_element['end_pos']]
#         other_interval = [interpretations[i]['start_pos'],
#                           interpretations[i]['end_pos']]

#         if is_overlaping(pop_element['start_pos'], other_interval):

#             # new_element = pop_element[0], max(pop_element[1], interpretations[i][1])
#             if method == 'best_score':
#                 if best_interp['best_entity'][1] < other_interp['best_entity'][1]:
#                     best_interp = other_interp
#             elif method == 'large_text':
#                 if len(best_interp['text']) < len(other_interp['text']):
#                     best_interp = other_interp
#             else:
#                 raise('Unknow method')
#             merged_list.append(new_element)
#         else:
#             merged_list.append(pop_element)
#             merged_list.append(interpretations[i])
#     return merged_list


def get_mentions_ner(text:str,nlp,model_type='flair') -> List[str]:

    if model_type=='flair':
        return get_mentions_flair(text,nlp)

    elif model_type == 'bert_transformers_pipeline':
        return get_mentions_bert_transformers_pipeline(text, nlp)
        

def get_mentions_bert_transformers_pipeline(text, ner_pipeline):
    """This function just standarize the output of the bert tarnsformers
    into our format. 

    It assumes pipeline is created like
    from transformers import pipeline
    ner_pipeline = pipeline('ner', model=output_dir, tokenizer=output_dir,ignore_labels=['O'],
    grouped_entities=True,ignore_subwords=True)
    """
    # the pipeline outputs something like this
    # [{'entity_group': 'bio',
    #   'score': 0.9999975,
    #   'word': 'hiv infection',
    #   'start': 22,
    #   'end': 35},
    #  {'entity_group': 'bio',
    #     'score': 0.9999923,
    #     'word': 'flu',
    #     'start': 37,
    #     'end': 40},

    res_pipeline=ner_pipeline(text)
    mentions = []
    results = []
    for res in res_pipeline:
        
        results.append({
            'text': res['word'],
            'start_pos': res['start'],
            'end_pos': res['end'],
        })
        mentions.append(res['word'])

    return mentions, results



def get_mentions_flair(text,nlp):
    sentence = Sentence(text)
    nlp.predict(sentence) # how to sent batches?

    return proc_flair_sentence

def proc_flair_sentence(sentence):

    mentions = []
    start_poss=[]
    end_poss = []

    last_end = -3
    i = 0
    for entity in sentence.to_dict(tag_type='ner')['entities']:
        #combine
        if (last_end+1) == entity['start_pos']:
            mentions[i-1] += ' ' + entity['text']
            end_poss[i-1] = entity['end_pos']
        else:
            mentions.append(entity['text'])
            i += 1
            start_poss.append(entity['start_pos'])
            end_poss.append(entity['end_pos'])
        last_end = entity['end_pos']

    #Pack all ina dict
    results = []
    for i,mention in enumerate(mentions): 
        results.append({
            'text':mention,
            'start_pos':start_poss[i],
            'end_pos':end_poss[i],
        })

    return mentions,results


def load_ontology_entity_linker():
    """Load the default ontology entity linker.
    """
    from dkoulinker.entity_ranking import DictionaryRanking, QueryEntityRanking
    import os
    from flair.models import SequenceTagger

    DATA_PATH = '/home/julio/repos/dkou_linker/'
    # loading dicitonary of commonness,
    print('Loading mention2pem dictionary ...')
    handle = open(
        os.path.join(DATA_PATH, 'data/pem/pem.pickle'), 'rb')
    mention2pem = pickle.load(handle)

    print('Loading entity description dictionary ...')
    handle_desc = open(
        os.path.join(DATA_PATH, 'data/pem/entity2description.pickle'), 'rb')
    entity2description = pickle.load(handle_desc)
    print('NUmber of entities: ', len(entity2description))

    print('Loading dictionary of term frequency ...')
    handle_desc = open(
        os.path.join(DATA_PATH, 'data/pem/mention_freq.pickle'), 'rb')
    mention2freq = pickle.load(handle_desc)
    print('Number of term in the collection: ', len(mention2freq))

    # given by create_term_req
    collection_size_terms = len(mention2pem)
    tagger = SequenceTagger.load(
        os.path.join(
            DATA_PATH, 'resources/taggers/sota-ner-flair/best-model.pt'))
    dictionarysearch_strategy = DictionaryRanking(mention2pem)
    queryranking_strategy = QueryEntityRanking(
        entity2description=entity2description,
        mention_freq=mention2freq,
        mention2pem=mention2pem
    )
    e_linker = EntityLinker(
        ranking_strategy=queryranking_strategy,
        ner_model=tagger,
        mention2pem=mention2pem,
        prune_overlapping_method='large_text'
    )
    return e_linker
