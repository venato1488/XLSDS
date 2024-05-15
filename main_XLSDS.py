import argparse
import sys
import os
import numpy as np
import torch
from torch import nn
from torch import Tensor
from torch.utils.data import DataLoader, ConcatDataset
import yaml
from data_utils_SSL import genSpoof_list,Dataset_ASVspoof2019_train,Dataset_ASVspoof2021_eval,genSpoof_list_ITW,Wav_Containing_Dataset_eval,genSpoof_list_MLAAD,Wav_Containing_Dataset_train
from model import Model
from tensorboardX import SummaryWriter
from core_scripts.startup_config import set_random_seed


__author__ = "Hemlata Tak"
__email__ = "tak@eurecom.fr"



def evaluate_accuracy(dev_loader, model, device):
    val_loss = 0.0
    num_total = 0.0
    model.eval()
    weight = torch.FloatTensor([0.1, 0.9]).to(device)
    criterion = nn.CrossEntropyLoss(weight=weight)
    for batch_x, batch_y in dev_loader:
        
        batch_size = batch_x.size(0)
        num_total += batch_size
        batch_x = batch_x.to(device)
        batch_y = batch_y.view(-1).type(torch.int64).to(device)
        batch_out = model(batch_x)
        
        batch_loss = criterion(batch_out, batch_y)
        val_loss += (batch_loss.item() * batch_size)
        
    val_loss /= num_total
   
    return val_loss


def produce_evaluation_file(dataset, model, device, save_path):
    data_loader = DataLoader(dataset, batch_size=14, shuffle=False, drop_last=False)
    num_correct = 0.0
    num_total = 0.0
    model.eval()
    
    fname_list = []
    key_list = []
    score_list = []
    
    for batch_x,utt_id in data_loader:
        fname_list = []
        score_list = []  
        batch_size = batch_x.size(0)
        batch_x = batch_x.to(device)
        
        batch_out = model(batch_x)
        
        batch_score = (batch_out[:, 1]  
                       ).data.cpu().numpy().ravel() 
        # add outputs
        fname_list.extend(utt_id)
        score_list.extend(batch_score.tolist())
        
        with open(save_path, 'a+') as fh:
            for f, cm in zip(fname_list,score_list):
                fh.write('{} {}\n'.format(f, cm))
        fh.close()   
    print('Scores saved to {}'.format(save_path))

def train_epoch(train_loader, model, lr,optim, device):
    running_loss = 0
    
    num_total = 0.0
    
    model.train()

    #set objective (Loss) functions
    weight = torch.FloatTensor([0.1, 0.9]).to(device)
    criterion = nn.CrossEntropyLoss(weight=weight)
    
    for batch_x, batch_y in train_loader:
       
        batch_size = batch_x.size(0)
        num_total += batch_size
        
        batch_x = batch_x.to(device)
        batch_y = batch_y.view(-1).type(torch.int64).to(device)
        batch_out = model(batch_x)
        
        batch_loss = criterion(batch_out, batch_y)
        
        running_loss += (batch_loss.item() * batch_size)
       
        optimizer.zero_grad()
        batch_loss.backward()
        optimizer.step()
       
    running_loss /= num_total
    
    return running_loss

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='XLSDS system')
    # Dataset
    parser.add_argument('--database_path', type=str, default='database/DF/', help='Change this to user\'s full directory address of LA database (ASVspoof2019- for training & development (used as validation), ASVspoof2021 DF for evaluation scores). We assume that all three ASVspoof 2019 LA train, LA dev and ASVspoof2021 DF eval data folders are in the same database_path directory.') 
    '''
    % database_path/
    %   |- DF
    %      |- ASVspoof2021_DF_eval/flac
    %      |- ASVspoof2019_LA_train/flac
    %      |- ASVspoof2019_LA_dev/flac
    %   |- ITW
    %      |- wav 
    %   |- MLAAD_GB
    %      |- wav
    '''

    parser.add_argument('--protocols_path', type=str, default='database/', help='Change with path to user\'s DF database protocols directory address')
    '''
    % protocols_path/
    %   |- ASVspoof_LA_cm_protocols
    %      |- ASVspoof2021.LA.cm.eval.trl.txt
    %      |- ASVspoof2019.LA.cm.dev.trl.txt 
    %      |- ASVspoof2019.LA.cm.train.trn.txt
 
    %   |- ASVspoof_DF_cm_protocols
    %      |- ASVspoof2021.DF.cm.eval.trl.txt
    %   |- ITW
    %      |- train_meta.txt
    %      |- dev_meta.txt
    %      |- eval_meta.txt
    %   |- MLAAD_GB
    %      |- train_meta.txt
    %      |- dev_meta.txt
    %      |- eval_meta.txt
  
    '''

    # Hyperparameters
    parser.add_argument('--batch_size', type=int, default=14)
    parser.add_argument('--num_epochs', type=int, default=100)
    parser.add_argument('--lr', type=float, default=0.000001)
    parser.add_argument('--weight_decay', type=float, default=0.0001)
    parser.add_argument('--loss', type=str, default='weighted_CCE')
    # model
    parser.add_argument('--seed', type=int, default=42, 
                        help='random seed (default: 1234)')
    
    parser.add_argument('--model_path', type=str,
                        default=None, help='Model checkpoint')
    parser.add_argument('--comment', type=str, default=None,
                        help='Comment to describe the saved model')
    # Auxiliary arguments
    parser.add_argument('--track', type=str, default='DF',choices=['LA', 'PA','DF'], help='LA/PA/DF')
    parser.add_argument('--eval_output', type=str, default=None,
                        help='Path to save the evaluation result')
    parser.add_argument('--eval', action='store_true', default=False,
                        help='eval mode')
    parser.add_argument('--is_eval', action='store_true', default=False,help='eval database')
    parser.add_argument('--eval_part', type=int, default=0)
    # backend options
    parser.add_argument('--cudnn-deterministic-toggle', action='store_false', \
                        default=True, 
                        help='use cudnn-deterministic? (default true)')    
    
    parser.add_argument('--cudnn-benchmark-toggle', action='store_true', \
                        default=False, 
                        help='use cudnn-benchmark? (default false)') 


    ##===================================================Rawboost data augmentation ======================================================================#

    parser.add_argument('--algo', type=int, default=3, 
                    help='Rawboost algos discriptions. 0: No augmentation 1: LnL_convolutive_noise, 2: ISD_additive_noise, 3: SSI_additive_noise, 4: series algo (1+2+3), \
                          5: series algo (1+2), 6: series algo (1+3), 7: series algo(2+3), 8: parallel algo(1,2) .default=0]')

    # LnL_convolutive_noise parameters 
    parser.add_argument('--nBands', type=int, default=5, 
                    help='number of notch filters.The higher the number of bands, the more aggresive the distortions is.[default=5]')
    parser.add_argument('--minF', type=int, default=20, 
                    help='minimum centre frequency [Hz] of notch filter.[default=20] ')
    parser.add_argument('--maxF', type=int, default=8000, 
                    help='maximum centre frequency [Hz] (<sr/2)  of notch filter.[default=8000]')
    parser.add_argument('--minBW', type=int, default=100, 
                    help='minimum width [Hz] of filter.[default=100] ')
    parser.add_argument('--maxBW', type=int, default=1000, 
                    help='maximum width [Hz] of filter.[default=1000] ')
    parser.add_argument('--minCoeff', type=int, default=10, 
                    help='minimum filter coefficients. More the filter coefficients more ideal the filter slope.[default=10]')
    parser.add_argument('--maxCoeff', type=int, default=100, 
                    help='maximum filter coefficients. More the filter coefficients more ideal the filter slope.[default=100]')
    parser.add_argument('--minG', type=int, default=0, 
                    help='minimum gain factor of linear component.[default=0]')
    parser.add_argument('--maxG', type=int, default=0, 
                    help='maximum gain factor of linear component.[default=0]')
    parser.add_argument('--minBiasLinNonLin', type=int, default=5, 
                    help=' minimum gain difference between linear and non-linear components.[default=5]')
    parser.add_argument('--maxBiasLinNonLin', type=int, default=20, 
                    help=' maximum gain difference between linear and non-linear components.[default=20]')
    parser.add_argument('--N_f', type=int, default=5, 
                    help='order of the (non-)linearity where N_f=1 refers only to linear components.[default=5]')

    # ISD_additive_noise parameters
    parser.add_argument('--P', type=int, default=10, 
                    help='Maximum number of uniformly distributed samples in [%].[defaul=10]')
    parser.add_argument('--g_sd', type=int, default=2, 
                    help='gain parameters > 0. [default=2]')

    # SSI_additive_noise parameters
    parser.add_argument('--SNRmin', type=int, default=10, 
                    help='Minimum SNR value for coloured additive noise.[defaul=10]')
    parser.add_argument('--SNRmax', type=int, default=40, 
                    help='Maximum SNR value for coloured additive noise.[defaul=40]')
    
    ##===================================================Rawboost data augmentation ======================================================================#
    

    if not os.path.exists('models'):
        os.mkdir('models')
    args = parser.parse_args()
 
    #make experiment reproducible
    set_random_seed(args.seed, args)
    
    track = args.track

    assert track in ['LA', 'PA','DF'], 'Invalid track given'

    #database
    prefix_2021 = 'ASVspoof2021.{}'.format(track)
    
    #define model saving path
    model_tag = 'model_{}_{}_{}_{}_{}'.format(
        track, args.loss, args.num_epochs, args.batch_size, args.lr)
    if args.comment:
        model_tag = model_tag + '_{}'.format(args.comment)
    model_save_path = os.path.join('models', model_tag)

    #set model save directory
    if not os.path.exists(model_save_path):
        os.mkdir(model_save_path)
    
    #GPU device
    device = 'cuda' if torch.cuda.is_available() else 'cpu'                  
    print('Device: {}'.format(device))
    
    model = Model(args,device)
    nb_params = sum([param.view(-1).size()[0] for param in model.parameters()])
    model =nn.DataParallel(model).to(device)
    print('nb_params:',nb_params)

    #set Adam optimizer
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr,weight_decay=args.weight_decay)
    
    if args.model_path:
        model.load_state_dict(torch.load(args.model_path,map_location=device))
        print('Model loaded : {}'.format(args.model_path))


    #evaluation 
    # To evaluate on ASVspoof 2021 DF eval set or ITW or MLAAD, the required dataset should be uncommented and the rest should be commented.
    
    """if args.eval:
        file_eval = genSpoof_list( dir_meta =  os.path.join(args.protocols_path+'ASVspoof_{}_cm_protocols/{}.cm.eval.trl.txt'.format(track,prefix_2021)),is_train=False,is_eval=True)
        print('no. of eval trials',len(file_eval))
        eval_set=Dataset_ASVspoof2021_eval(list_IDs = file_eval,base_dir = os.path.join(args.database_path+'ASVspoof2021_{}_eval/'.format(args.track)))
        produce_evaluation_file(eval_set, model, device, args.eval_output)
        sys.exit(0)"""

    """if args.is_eval:
        file_eval = genSpoof_list_ITW(metadata_file_path = r'database\ITW\eval_meta.txt',is_train=False,is_eval=True)
        print('no. of eval trials',len(file_eval))
        eval_set=Wav_Containing_Dataset_eval(list_IDs = file_eval,base_dir = 'database/ITW/wav/')
        produce_evaluation_file(eval_set, model, device, args.eval_output)
        sys.exit(0)"""
    
    if args.is_eval:
        file_eval = genSpoof_list_MLAAD(metadata_dir = r'database\MLAAD_GB_v2\eval_meta.txt',is_train=False,is_eval=True)
        print('no. of eval trials',len(file_eval))
        
        eval_set=Wav_Containing_Dataset_eval(list_IDs = file_eval,base_dir = 'database/MLAAD_GB_v2/wav/')
        produce_evaluation_file(eval_set, model, device, args.eval_output)
        sys.exit(0)
    
    
    

     
    # define train dataloader
    d_label_trn,file_train = genSpoof_list(dir_meta =  os.path.join(args.protocols_path+'ASVspoof_LA_cm_protocols/ASVspoof2019.LA.cm.train.trn.txt'),is_train=True,is_eval=False)   
    print('no. of training trials',len(file_train))   
    train_set=Dataset_ASVspoof2019_train(args,list_IDs = file_train,labels = d_label_trn,base_dir = os.path.join(args.database_path+'ASVspoof2019_LA_train/'),algo=args.algo)
    train_loader = DataLoader(train_set, batch_size=args.batch_size,num_workers=8, shuffle=True,drop_last = True)
    
    d_label_trn_ITW,file_train_ITW = genSpoof_list_ITW( metadata_file_path = r'database\ITW\train_meta.txt',is_train=True,is_eval=False)
    itw_and_asv_train_len = len(file_train_ITW) + len(file_train)

    d_label_trn_MLAAD,file_train_MLAAD = genSpoof_list_MLAAD(metadata_dir = r'database\MLAAD_GB_v2\train_meta.txt',is_train=True,is_eval=False)
    total_train_len = itw_and_asv_train_len + len(file_train_MLAAD)
    del d_label_trn
    

    # define dev (validation) dataloader
    
    d_label_dev,file_dev = genSpoof_list( dir_meta =  os.path.join(args.protocols_path+'ASVspoof_LA_cm_protocols/ASVspoof2019.LA.cm.dev.trl.txt'),is_train=False,is_eval=False)    
    print('no. of validation trials',len(file_dev))   
    dev_set = Dataset_ASVspoof2019_train(args,list_IDs = file_dev,labels = d_label_dev,base_dir = os.path.join(args.database_path+'ASVspoof2019_LA_dev/'),algo=args.algo)
    dev_loader = DataLoader(dev_set, batch_size=args.batch_size,num_workers=8, shuffle=False)
    
    d_label_dev_ITW,file_dev_ITW = genSpoof_list_ITW( metadata_file_path = r'database\ITW\dev_meta.txt',is_train=False,is_eval=False)
    itw_and_asv_dev_len = len(file_dev_ITW) + len(file_dev)

    d_label_dev_MLAAD,file_dev_MLAAD = genSpoof_list_MLAAD(metadata_dir = r'database\MLAAD_GB_v2\dev_meta.txt',is_train=False,is_eval=False)
    total_dev_len = itw_and_asv_dev_len + len(file_dev_MLAAD)

    del d_label_dev

    
    # Training and validation 
    num_epochs = args.num_epochs
    writer = SummaryWriter('logs/{}'.format(model_tag))
    best_val_loss = float('inf')
    itw_added = False
    mlaad_added = False
    patience = 3
    epoch_no_improve = 0

    print('Training...')
    for epoch in range(num_epochs):
        running_loss = train_epoch(train_loader,model, args.lr,optimizer, device)
        val_loss = evaluate_accuracy(dev_loader, model, device)
        writer.add_scalar('val_loss', val_loss, epoch)
        writer.add_scalar('loss', running_loss, epoch)
        print('\nEpoch: {} - Running loss: {} - Validation Loss: {} '.format(epoch,running_loss,val_loss))  

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            epoch_no_improve = 0
        else:
            epoch_no_improve += 1
        
        
        if not itw_added and epoch_no_improve >= patience:
            
            asv_and_itw_train = ConcatDataset([train_set, Wav_Containing_Dataset_train(list_IDs = file_train_ITW,
                                                                                       base_dir = 'database/ITW/wav/', 
                                                                                       algo=args.algo,
                                                                                       labels=d_label_trn_ITW,
                                                                                       args=args)])
            train_loader = DataLoader(asv_and_itw_train, batch_size=args.batch_size,num_workers=8, shuffle=True,drop_last = True)
            asv_and_itw_dev = ConcatDataset([dev_set, Wav_Containing_Dataset_train(list_IDs = file_dev_ITW,
                                                                                   base_dir = 'database/ITW/wav/', 
                                                                                   algo=args.algo,
                                                                                   labels=d_label_dev_ITW,
                                                                                   args=args)])
            dev_loader = DataLoader(asv_and_itw_dev, batch_size=args.batch_size,num_workers=8, shuffle=False)
            del train_set, dev_set
            print('ITW data added\nUpdated no. of training trials: ',str(itw_and_asv_train_len))
            print('Updated no. of validation trials: ',str(itw_and_asv_dev_len))
            itw_added = True
            epoch_no_improve = 0
            best_val_loss = float('inf')
            
        elif not mlaad_added and epoch_no_improve >= patience:
            asv_ITW_and_MLAAD_train = ConcatDataset([asv_and_itw_train, Wav_Containing_Dataset_train(list_IDs = file_train_MLAAD,
                                                                                                     base_dir = 'database/MLAAD_GB_v2/wav/', 
                                                                                                     algo=args.algo,
                                                                                                     labels=d_label_trn_MLAAD,
                                                                                                     args=args)])
            train_loader = DataLoader(asv_ITW_and_MLAAD_train, batch_size=args.batch_size,num_workers=8, shuffle=True,drop_last = True)
            asv_ITW_and_MLAAD_dev = ConcatDataset([asv_and_itw_dev, Wav_Containing_Dataset_train(list_IDs = file_dev_MLAAD,
                                                                                                 base_dir = 'database/MLAAD_GB_v2/wav/', 
                                                                                                 algo=args.algo,
                                                                                                 labels=d_label_dev_MLAAD,
                                                                                                 args=args)])
            dev_loader = DataLoader(asv_ITW_and_MLAAD_dev, batch_size=args.batch_size,num_workers=8, shuffle=False)
            del asv_and_itw_train, asv_and_itw_dev
            print('MLAAD data added\nUpdated no. of training trials: ', str(total_train_len))
            print('Updated no. of validation trials: ', str(total_dev_len))
            mlaad_added = True
            epoch_no_improve = 0
            best_val_loss = float('inf')
        


        latest_model_path = os.path.join(model_save_path, 'epoch_{}.pth'.format(epoch))
        torch.save(model.state_dict(), latest_model_path)
        if itw_added and mlaad_added and epoch_no_improve >= patience:
            break